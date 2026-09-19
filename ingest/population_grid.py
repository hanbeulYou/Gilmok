"""Read the verified Seoul 250m grid; derive missing cells only after full rule validation."""

import re
from pathlib import Path

import duckdb


def grid_rows(shapefile: Path, observed_cells: set[str]) -> list[dict]:
    with duckdb.connect() as connection:
        connection.execute("LOAD spatial")
        connection.execute("create table grid as select * from ST_Read(?)", [str(shapefile)])
        schema = dict((row[0], row[1]) for row in connection.execute("describe grid").fetchall())
        if schema.get("geom") != "GEOMETRY('EPSG:5179')":
            raise ValueError("Grid CRS must be verified EPSG:5179")
        # CELL_ID = 다사 + easting/10 (4 digits) + northing/10 (4 digits).
        # Validate this observed rule against EVERY supplied geometry and center first.
        invalid = connection.execute(
            "select count(*) from grid where "
            "geom is null or CELL_X is null or CELL_Y is null or ST_IsEmpty(geom) "
            "or not regexp_full_match(CELL_ID, '다사[0-9]{8}') "
            "or ST_XMin(geom) <> 900000 + try_cast(substr(CELL_ID,3,4) as int)*10 "
            "or ST_YMin(geom) <> 1900000 + try_cast(substr(CELL_ID,7,4) as int)*10 "
            "or ST_XMax(geom)-ST_XMin(geom)<>250 or ST_YMax(geom)-ST_YMin(geom)<>250 "
            "or ST_Area(geom)<>62500 or not ST_IsValid(geom) "
            "or CELL_X<>ST_XMin(geom)+125 or CELL_Y<>ST_YMin(geom)+125"
        ).fetchone()[0]
        count, unique = connection.execute(
            "select count(*),count(distinct CELL_ID) from grid"
        ).fetchone()
        if invalid or not count or count != unique:
            raise ValueError("Grid file does not verify the documented 250m CELL_ID rule")
        result = connection.execute(
            "select CELL_ID, ST_AsText(ST_Transform(geom,'EPSG:5179','EPSG:4326',"
            "always_xy:=true)) from grid order by CELL_ID"
        ).fetchall()
        output = [{"cell_id": cell, "wkt": wkt, "boundary_generated": False}
                  for cell, wkt in result]
        known = {row["cell_id"] for row in output}
        bounds = connection.execute(
            "select min(ST_XMin(geom)),min(ST_YMin(geom)),max(ST_XMax(geom)),max(ST_YMax(geom)) "
            "from grid"
        ).fetchone()
        for cell in sorted(observed_cells - known):
            if not re.fullmatch(r"다사\d{8}", cell):
                raise ValueError("Unverified CELL_ID family; cannot generate its boundary")
            x = 900000 + int(cell[2:6]) * 10
            y = 1900000 + int(cell[6:10]) * 10
            if (x % 250 or y % 250 or not
                    (bounds[0] <= x and x + 250 <= bounds[2]
                     and bounds[1] <= y and y + 250 <= bounds[3])):
                raise ValueError("Cell is outside the verified grid rule or extent")
            wkt = connection.execute(
                "select ST_AsText(ST_Transform(ST_MakeEnvelope(?,?,?,?),"
                "'EPSG:5179','EPSG:4326',always_xy:=true))", [x, y, x + 250, y + 250]
            ).fetchone()[0]
            output.append({"cell_id": cell, "wkt": wkt, "boundary_generated": True})
        return output
