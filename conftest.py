import warnings

# apply at module level so filter is active before test collection imports run_1
warnings.filterwarnings("ignore", message=".*shapely.geos.*", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*shapely.*", category=DeprecationWarning)

def pytest_configure(config):
    warnings.filterwarnings("ignore", message=".*shapely.geos.*", category=DeprecationWarning)
    warnings.filterwarnings("ignore", message=".*shapely.*", category=DeprecationWarning)
