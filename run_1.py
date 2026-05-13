#-------------------------------------------------------------------------------
# Name:        CCTV
# Purpose:
# Author:
# Created:     28-06-2021
# Copyright:   ISOVIST CU
# Licence:     sittinun2tb@gmail.com
#-------------------------------------------------------------------------------
import os, sys, math, importlib.util

# point to rasterio's bundled proj_data BEFORE any geo library initialises PROJ
_spec = importlib.util.find_spec('rasterio')
if _spec:
    _proj_data = os.path.join(os.path.dirname(_spec.origin), 'proj_data')
    os.environ['PROJ_DATA'] = _proj_data  # PROJ 9+
    os.environ['PROJ_LIB']  = _proj_data  # PROJ 8

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

import matplotlib as mlp
import matplotlib.pyplot as plt
from matplotlib import rcParams
import contextily as ctx

rcParams['font.family'] = 'sans-serif'
rcParams['font.sans-serif'] = ['Tahoma']

FOV_DEGREES = 109       # camera field-of-view in degrees
ANGLE_STEP = 0.1        # ray casting resolution in degrees
FULL_ROTATION = 360     # degrees
GRID_LENGTH = 100       # analysis grid cell height in metres
GRID_WIDTH = 120        # analysis grid cell width in metres


class IsovistAnalysis:
    def __init__(self, infile_bld, infile_cctv):
        self.dir = os.path.dirname(sys.argv[0])
        self.bld = os.path.join(self.dir, infile_bld)
        self.cctv = os.path.join(self.dir, infile_cctv)

        self.bld_utn_gdf = None
        self.cctv_utn_gdf = None

        self.cctv_1_gdf = None
        self.x1 = None
        self.y1 = None

        self.poly_cctv_gdf = None
        self.bld_union_ints = None
        self.polyBlock_gdf = None
        self.visible_gdf = None
        self.polyVisible = None

        self.cctv_outdoor = None
        self.numcctv_indoor = None

        self.result = 0

    def OpenFile(self):
        if not os.path.exists(self.bld):
            raise FileNotFoundError("%s does not exist" % self.bld)
        bld_gdf = gpd.read_file(self.bld)
        if bld_gdf.crs is None:
            bld_gdf = bld_gdf.set_crs('EPSG:4326')
        self.bld_utn_gdf = bld_gdf.to_crs('EPSG:32647')

        if not os.path.exists(self.cctv):
            raise FileNotFoundError("%s does not exist" % self.cctv)
        cctv_gdf = gpd.read_file(self.cctv)
        if cctv_gdf.crs is None:
            cctv_gdf = cctv_gdf.set_crs('EPSG:4326')
        self.cctv_utn_gdf = cctv_gdf.to_crs('EPSG:32647')

        return {'BLD': self.bld_utn_gdf, 'CCTV': self.cctv_utn_gdf}

    def ListCCTV(self):
        if self.cctv_outdoor is None:
            self.cctv_outdoor = gpd.overlay(self.cctv_utn_gdf, self.bld_utn_gdf, how='difference')
            self.numcctv_indoor = len(self.cctv_utn_gdf) - len(self.cctv_outdoor)
            print("CCTV InDoor: %s" % self.numcctv_indoor)
        return self.cctv_outdoor

    def nearest_cctv(self):
        obj_buff_cctv = self.poly_cctv_gdf.geometry.values[0]
        list_bld = [obj for obj in self.bld_utn_gdf.geometry.values if obj_buff_cctv.intersects(obj)]
        if not list_bld:
            print("Warning: no buildings found within buffer — isovist will be unobstructed")
        return list_bld

    def TrigonAngleDistance(self, azimuth, distance):
        radian = azimuth * math.pi / 180
        x_target = self.x1 + math.cos(radian) * distance
        y_target = self.y1 + math.sin(radian) * distance
        return Point(x_target, y_target)

    def View2BlD(self, pFar):
        line = LineString([Point(self.x1, self.y1), pFar])
        geoms = line.intersection(self.bld_union_ints)
        if not geoms.is_empty:
            if geoms.geom_type == "MultiLineString":
                chkPoint = [point for line in geoms.geoms for point in line.coords]
            elif geoms.geom_type == "LineString":
                chkPoint = geoms.coords
            else:
                # Point / MultiPoint / GeometryCollection — treat ray as unobstructed
                return LineString([Point(self.x1, self.y1), pFar])
            geoms = min(
                [(Point(p[0], p[1]), LineString([Point(self.x1, self.y1), Point(p[0], p[1])]).length)
                 for p in chkPoint],
                key=lambda t: t[1]
            )[0]
        else:
            geoms = pFar
        return LineString([Point(self.x1, self.y1), geoms])

    def RUN(self, idx, rays):
        listcctv = self.ListCCTV()

        if idx not in listcctv.index:
            return None
        row = listcctv.loc[idx]
        print("CCTV ID:", idx)

        self.cctv_1_gdf = gpd.GeoDataFrame(
            crs='EPSG:32647',
            geometry=gpd.points_from_xy([row['geometry'].x], [row['geometry'].y])
        )
        self.x1 = self.cctv_1_gdf.geometry.values.x[0]
        self.y1 = self.cctv_1_gdf.geometry.values.y[0]

        poly_cctv = self.cctv_1_gdf.buffer(rays)
        self.poly_cctv_gdf = gpd.GeoDataFrame(crs='EPSG:32647', geometry=poly_cctv)

        listBlD = self.nearest_cctv()
        bld_union_gdf = gpd.GeoDataFrame(
            geometry=gpd.GeoSeries([unary_union(listBlD)]), crs='EPSG:32647'
        )
        self.bld_union_ints = self.poly_cctv_gdf.geometry.values[0].intersection(bld_union_gdf.geometry.values[0])

        listVisible = []
        listBoundary = []
        ang_view = FOV_DEGREES / 2

        listBoundary.append(self.cctv_1_gdf.geometry.values[0])

        for deg in np.arange(0, FULL_ROTATION, ANGLE_STEP):
            if float(row['rotation']) - ang_view <= deg <= float(row['rotation']) + ang_view:
                theta = 90 - deg
                pnt_curve = self.TrigonAngleDistance(theta, rays)
                line_v = self.View2BlD(pnt_curve)
                pnt_visible = list(line_v.coords)[1]
                listBoundary.append(Point(pnt_visible))
                listVisible.append(line_v)

        listBoundary.append(self.cctv_1_gdf.geometry.values[0])

        self.polyVisible = Polygon([[p.x, p.y] for p in listBoundary])
        self.polyBlock_gdf = gpd.GeoDataFrame(crs='EPSG:32647', geometry=[self.polyVisible])
        self.visible_gdf = gpd.GeoDataFrame(crs='EPSG:32647', geometry=listVisible)
        self.result = len(self.visible_gdf)

        return self.polyVisible


if __name__ == "__main__":
    print("numpy=%s" % np.__version__)
    print("pandas=%s" % pd.__version__)
    print("geopandas=%s" % gpd.__version__)
    print("matplotlib=%s" % mlp.__version__)

    dir_app = os.path.dirname(sys.argv[0])
    bld = r'data/bld_siam2_merge.geojson'
    cctv = r'data/cctv_siam_azimuth2.geojson'
    rays = 80
    _, ax = plt.subplots()

    CLASSP = IsovistAnalysis(bld, cctv)
    DictObj = CLASSP.OpenFile()

    xmin, ymin, xmax, ymax = DictObj['BLD'].geometry.total_bounds
    cols = list(np.arange(xmin, xmax + GRID_WIDTH, GRID_WIDTH))
    rows = list(np.arange(ymin, ymax + GRID_LENGTH, GRID_LENGTH))

    polygons = []
    for x in cols[:-1]:
        for y in rows[:-1]:
            polygons.append(Polygon([(x, y), (x + GRID_WIDTH, y), (x + GRID_WIDTH, y + GRID_LENGTH), (x, y + GRID_LENGTH)]))

    grid = gpd.GeoDataFrame({'geometry': polygons}, crs='EPSG:32647')
    grid.to_file(os.path.join(dir_app, "data", "grid.shp"))

    listcctv = CLASSP.ListCCTV()
    POLYVISIBLE = []

    for i in listcctv.index:
        poly = CLASSP.RUN(i, rays)
        if poly is not None:
            POLYVISIBLE.append(poly)

    POLYVISIBLE_gdf = gpd.GeoDataFrame(crs='EPSG:32647', geometry=POLYVISIBLE).to_crs('EPSG:3857')
    outFile = os.path.join(dir_app, 'data', "output_file.gpkg")
    POLYVISIBLE_gdf.to_file(outFile, layer='cctv_isovist', driver='GPKG')

    ax.set_title("CCTV Count. %s | Rays: %s | At สยามสแควร์" % (len(POLYVISIBLE_gdf), rays))

    POLYVISIBLE_gdf.plot(ax=ax, color='yellow', alpha=.5)
    DictObj['CCTV'].to_crs('EPSG:3857').plot(ax=ax, color='red', marker=".", markersize=50)
    DictObj['BLD'].to_crs('EPSG:3857').plot(ax=ax, color='green')

    ctx.add_basemap(ax, crs='EPSG:3857', source=ctx.providers.Esri.WorldImagery)

    plt.show()
