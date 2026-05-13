import math
import os
import pytest
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union

from run_1 import IsovistAnalysis

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
BLD_FILE  = os.path.join(DATA_DIR, 'bld_siam2_merge.geojson')
CCTV_FILE = os.path.join(DATA_DIR, 'cctv_siam_azimuth2.geojson')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_analysis():
    """Return an IsovistAnalysis with __init__ bypassed (no file I/O)."""
    obj = IsovistAnalysis.__new__(IsovistAnalysis)
    obj.bld_utn_gdf   = None
    obj.cctv_utn_gdf  = None
    obj.cctv_1_gdf    = None
    obj.x1 = obj.y1   = None
    obj.poly_cctv_gdf = None
    obj.bld_union_ints = None
    obj.polyBlock_gdf  = None
    obj.visible_gdf    = None
    obj.polyVisible    = None
    obj.cctv_outdoor   = None
    obj.numcctv_indoor = None
    obj.result         = 0
    return obj


def set_origin(obj, x=0.0, y=0.0):
    obj.x1, obj.y1 = x, y


# ---------------------------------------------------------------------------
# TrigonAngleDistance
# ---------------------------------------------------------------------------

class TestTrigonAngleDistance:

    def test_east(self):
        obj = make_analysis()
        set_origin(obj)
        p = obj.TrigonAngleDistance(azimuth=0, distance=10)
        assert abs(p.x - 10.0) < 1e-6
        assert abs(p.y -  0.0) < 1e-6

    def test_north(self):
        obj = make_analysis()
        set_origin(obj)
        p = obj.TrigonAngleDistance(azimuth=90, distance=10)
        assert abs(p.x -  0.0) < 1e-6
        assert abs(p.y - 10.0) < 1e-6

    def test_diagonal(self):
        obj = make_analysis()
        set_origin(obj)
        p = obj.TrigonAngleDistance(azimuth=45, distance=10)
        expected = 10 * math.cos(math.radians(45))
        assert abs(p.x - expected) < 1e-6
        assert abs(p.y - expected) < 1e-6

    def test_distance_preserved(self):
        obj = make_analysis()
        set_origin(obj, x=100.0, y=200.0)
        for az in [0, 45, 90, 135, 180, 270]:
            p = obj.TrigonAngleDistance(az, 50)
            dist = Point(obj.x1, obj.y1).distance(p)
            assert abs(dist - 50.0) < 1e-6, f"azimuth={az} gave distance={dist}"

    def test_offset_origin(self):
        obj = make_analysis()
        set_origin(obj, x=500.0, y=1000.0)
        p = obj.TrigonAngleDistance(azimuth=0, distance=20)
        assert abs(p.x - 520.0) < 1e-6
        assert abs(p.y - 1000.0) < 1e-6

    def test_zero_distance(self):
        obj = make_analysis()
        set_origin(obj, x=5.0, y=5.0)
        p = obj.TrigonAngleDistance(azimuth=45, distance=0)
        assert abs(p.x - 5.0) < 1e-6
        assert abs(p.y - 5.0) < 1e-6


# ---------------------------------------------------------------------------
# View2BlD
# ---------------------------------------------------------------------------

class TestView2BlD:

    def _make(self, x=0.0, y=0.0):
        obj = make_analysis()
        set_origin(obj, x, y)
        return obj

    def test_open_space_returns_far_point(self):
        """No building — ray should reach pFar unchanged."""
        obj = self._make()
        obj.bld_union_ints = Polygon()   # empty geometry
        pFar = Point(10, 0)
        line = obj.View2BlD(pFar)
        end = list(line.coords)[1]
        assert abs(end[0] - 10.0) < 1e-6
        assert abs(end[1] -  0.0) < 1e-6

    def test_building_blocks_ray(self):
        """Building wall at x=5 should stop ray before pFar=10."""
        obj = self._make()
        wall = Polygon([(4, -1), (6, -1), (6, 1), (4, 1)])
        obj.bld_union_ints = wall
        pFar = Point(10, 0)
        line = obj.View2BlD(pFar)
        end_x = list(line.coords)[1][0]
        assert end_x < 10.0, "ray should be blocked before pFar"
        assert end_x >= 4.0, "ray should not stop before the wall"

    def test_multilinestring_intersection(self):
        """Ray through two separate buildings → MultiLineString intersection → stop at closest."""
        obj = self._make()
        # two separate polygon buildings along the ray path (x-axis)
        bld_near = Polygon([(2, -1), (4, -1), (4, 1), (2, 1)])   # x=2–4
        bld_far  = Polygon([(6, -1), (8, -1), (8, 1), (6, 1)])   # x=6–8
        obj.bld_union_ints = unary_union([bld_near, bld_far])     # MultiPolygon
        pFar = Point(10, 0)
        line = obj.View2BlD(pFar)
        end_x = list(line.coords)[1][0]
        assert abs(end_x - 2.0) < 1e-3, "should stop at near face of closest building (x=2)"

    def test_geometry_collection_treated_as_unobstructed(self):
        """GeometryCollection edge case — ray should reach pFar."""
        from shapely.geometry import GeometryCollection
        obj = self._make()
        obj.bld_union_ints = GeometryCollection([Point(5, 0), LineString([(5,-1),(5,1)])])
        pFar = Point(10, 0)
        line = obj.View2BlD(pFar)
        end = list(line.coords)[1]
        assert abs(end[0] - 10.0) < 1e-6

    def test_return_type_is_linestring(self):
        obj = self._make()
        obj.bld_union_ints = Polygon()
        line = obj.View2BlD(Point(5, 5))
        assert isinstance(line, LineString)

    def test_origin_is_start_of_line(self):
        obj = self._make(x=100.0, y=200.0)
        obj.bld_union_ints = Polygon()
        line = obj.View2BlD(Point(110, 200))
        start = list(line.coords)[0]
        assert abs(start[0] - 100.0) < 1e-6
        assert abs(start[1] - 200.0) < 1e-6


# ---------------------------------------------------------------------------
# nearest_cctv
# ---------------------------------------------------------------------------

class TestNearestCCTV:

    def _make_with_buildings(self, buffer_radius=50):
        obj = make_analysis()
        set_origin(obj, x=0.0, y=0.0)

        cctv_pt = gpd.GeoDataFrame(
            crs='EPSG:32647', geometry=gpd.points_from_xy([0.0], [0.0])
        )
        obj.poly_cctv_gdf = gpd.GeoDataFrame(
            crs='EPSG:32647', geometry=cctv_pt.buffer(buffer_radius)
        )

        bld_inside  = Polygon([( 10,-5),( 20,-5),( 20, 5),( 10, 5)])
        bld_outside = Polygon([(200,-5),(210,-5),(210, 5),(200, 5)])
        obj.bld_utn_gdf = gpd.GeoDataFrame(
            crs='EPSG:32647', geometry=[bld_inside, bld_outside]
        )
        return obj

    def test_returns_only_buildings_in_buffer(self):
        obj = self._make_with_buildings(buffer_radius=50)
        result = obj.nearest_cctv()
        assert len(result) == 1

    def test_no_buildings_returns_empty_list(self):
        obj = self._make_with_buildings(buffer_radius=5)
        result = obj.nearest_cctv()
        assert result == []

    def test_multiple_buildings_in_buffer(self):
        obj = make_analysis()
        set_origin(obj, x=0.0, y=0.0)
        cctv_pt = gpd.GeoDataFrame(
            crs='EPSG:32647', geometry=gpd.points_from_xy([0.0], [0.0])
        )
        obj.poly_cctv_gdf = gpd.GeoDataFrame(
            crs='EPSG:32647', geometry=cctv_pt.buffer(100)
        )
        buildings = [
            Polygon([(10,-5),(20,-5),(20,5),(10,5)]),
            Polygon([(30,-5),(40,-5),(40,5),(30,5)]),
            Polygon([(50,-5),(60,-5),(60,5),(50,5)]),
        ]
        obj.bld_utn_gdf = gpd.GeoDataFrame(crs='EPSG:32647', geometry=buildings)
        result = obj.nearest_cctv()
        assert len(result) == 3

    def test_warns_when_no_buildings(self, capsys):
        obj = self._make_with_buildings(buffer_radius=5)
        obj.nearest_cctv()
        captured = capsys.readouterr()
        assert "Warning" in captured.out


# ---------------------------------------------------------------------------
# OpenFile
# ---------------------------------------------------------------------------

class TestOpenFile:

    @pytest.mark.skipif(
        not os.path.exists(BLD_FILE) or not os.path.exists(CCTV_FILE),
        reason="data files not found"
    )
    def test_loads_real_files(self):
        obj = IsovistAnalysis.__new__(IsovistAnalysis)
        obj.bld  = BLD_FILE
        obj.cctv = CCTV_FILE
        result = obj.OpenFile()
        assert 'BLD'  in result
        assert 'CCTV' in result
        assert result['BLD'].crs.to_epsg()  == 32647
        assert result['CCTV'].crs.to_epsg() == 32647

    def test_missing_bld_raises(self, tmp_path):
        obj = IsovistAnalysis.__new__(IsovistAnalysis)
        obj.bld  = str(tmp_path / 'missing_bld.geojson')
        obj.cctv = str(tmp_path / 'missing_cctv.geojson')
        with pytest.raises(FileNotFoundError):
            obj.OpenFile()

    def test_missing_cctv_raises(self, tmp_path):
        import json
        bld_path = tmp_path / 'bld.geojson'
        bld_path.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [
                    [[100.5, 13.7],[100.6, 13.7],[100.6, 13.8],[100.5, 13.8],[100.5, 13.7]]
                ]},
                "properties": {}
            }]
        }))
        obj = IsovistAnalysis.__new__(IsovistAnalysis)
        obj.bld  = str(bld_path)
        obj.cctv = str(tmp_path / 'missing_cctv.geojson')
        with pytest.raises(FileNotFoundError):
            obj.OpenFile()


# ---------------------------------------------------------------------------
# ListCCTV
# ---------------------------------------------------------------------------

class TestListCCTV:

    def _make_loaded(self):
        obj = make_analysis()
        cctv_inside  = Point(100, 100)
        cctv_outside = Point(500, 500)
        bld = Polygon([(90,90),(110,90),(110,110),(90,110)])

        obj.cctv_utn_gdf = gpd.GeoDataFrame(
            {'rotation': [0, 90]}, crs='EPSG:32647',
            geometry=[cctv_inside, cctv_outside]
        )
        obj.bld_utn_gdf = gpd.GeoDataFrame(crs='EPSG:32647', geometry=[bld])
        return obj

    def test_filters_indoor_cctv(self):
        obj = self._make_loaded()
        outdoor = obj.ListCCTV()
        assert len(outdoor) == 1

    def test_numcctv_indoor_is_set(self):
        obj = self._make_loaded()
        obj.ListCCTV()
        assert obj.numcctv_indoor == 1

    def test_result_is_cached(self):
        obj = self._make_loaded()
        first  = obj.ListCCTV()
        second = obj.ListCCTV()
        assert first is second  # same object — not recomputed


# ---------------------------------------------------------------------------
# RUN (integration)
# ---------------------------------------------------------------------------

class TestRUN:

    def _make_ready(self):
        obj = make_analysis()

        cctv_pt = Point(0, 0)
        bld = Polygon([(30,-10),(50,-10),(50,10),(30,10)])

        obj.cctv_utn_gdf = gpd.GeoDataFrame(
            {'rotation': [0.0]}, crs='EPSG:32647', geometry=[cctv_pt]
        )
        obj.bld_utn_gdf = gpd.GeoDataFrame(crs='EPSG:32647', geometry=[bld])
        return obj

    def test_returns_polygon(self):
        obj = self._make_ready()
        result = obj.RUN(idx=0, rays=80)
        assert isinstance(result, Polygon)

    def test_invalid_index_returns_none(self):
        obj = self._make_ready()
        obj.ListCCTV()
        result = obj.RUN(idx=999, rays=80)
        assert result is None

    def test_polygon_contains_cctv_origin(self):
        obj = self._make_ready()
        result = obj.RUN(idx=0, rays=80)
        assert result.contains(Point(0, 0)) or result.touches(Point(0, 0))

    def test_result_count_matches_visible_rays(self):
        obj = self._make_ready()
        obj.RUN(idx=0, rays=80)
        assert obj.result == len(obj.visible_gdf)

##########################################
# การรัน แบบ integration test (ทดสอบการทำงานร่วมกันของหลายๆ method)
#>> python -m pytest test_isovist.py -v