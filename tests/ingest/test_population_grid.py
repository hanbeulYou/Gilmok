from pathlib import Path

import duckdb
import pytest

from ingest.population_grid import grid_rows


@pytest.fixture(scope="module")
def spatial():
    connection = duckdb.connect()
    connection.execute("INSTALL spatial; LOAD spatial")
    yield connection
    connection.close()


def write_grid(connection, directory: Path, *, crs="EPSG:5179", shift=0):
    path = directory / "grid.shp"
    connection.execute(
        "create or replace table fixture_cells as "
        "select '다사50005000' as CELL_ID,950125 as CELL_X,1950125 as CELL_Y,"
        "ST_MakeEnvelope(950000+?,1950000,950250+?,1950250) as geom "
        "union all select '다사50505050',950625,1950625,"
        "ST_MakeEnvelope(950500,1950500,950750,1950750)", [shift, shift]
    )
    # Test-only known CRS values; fixture files have actual SHP/DBF/PRJ components.
    connection.execute(
        "copy fixture_cells to ? with (format GDAL, driver 'ESRI Shapefile', SRS '"
        + crs + "', LAYER_CREATION_OPTIONS ('ENCODING=UTF-8'))", [str(path)]
    )
    return path


def test_verified_grid_can_fill_a_missing_cell_without_guessing(spatial, tmp_path):
    path = write_grid(spatial, tmp_path)
    rows = grid_rows(path, {"다사50255025"})
    assert len(rows) == 3
    generated = [row for row in rows if row["boundary_generated"]]
    assert len(generated) == 1
    assert generated[0]["cell_id"] == "다사50255025"
    # Independent reverse projection checks both the origin and longitude/latitude order.
    x, y, area = spatial.execute(
        "with g as (select ST_Transform(ST_GeomFromText(?), 'EPSG:4326','EPSG:5179',"
        "always_xy:=true) as geom) select ST_XMin(geom),ST_YMin(geom),ST_Area(geom) from g",
        [generated[0]["wkt"]],
    ).fetchone()
    assert (x, y) == pytest.approx((950250, 1950250), abs=0.001)
    assert area == pytest.approx(62500, abs=0.001)


@pytest.mark.parametrize("cell", ["unknown", "다사50015000", "다사99999999"])
def test_grid_rejects_unknown_rule_or_extent(spatial, tmp_path, cell):
    path = write_grid(spatial, tmp_path)
    with pytest.raises(ValueError, match="Unverified|outside"):
        grid_rows(path, {cell})


def test_grid_rejects_changed_source_geometry(spatial, tmp_path):
    path = write_grid(spatial, tmp_path, shift=1)
    with pytest.raises(ValueError, match="does not verify"):
        grid_rows(path, {"다사50255025"})


def test_grid_rejects_wrong_crs(spatial, tmp_path):
    path = write_grid(spatial, tmp_path, crs="EPSG:5186")
    with pytest.raises(ValueError, match="CRS"):
        grid_rows(path, {"다사50255025"})
