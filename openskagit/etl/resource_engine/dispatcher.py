from .sql_builder import SQLBuilder

class MetricDispatcher:

    @staticmethod
    def build_sql(metric, parcel_geom, table, config):
        geom_col = config["geometry_column"]

        if metric == "intersects_boolean":
            return SQLBuilder.intersects_boolean(parcel_geom, f"{table}.{geom_col}")

        if metric == "intersects_attribute":
            col = config["source_column"]
            return SQLBuilder.intersects_attribute(parcel_geom, f"{table}.{geom_col}", col).replace("{table}", table)

        if metric == "nearest_distance":
            return SQLBuilder.nearest_distance(parcel_geom, f"{table}.{geom_col}").replace("{table}", table)

        if metric == "nearest_attribute":
            col = config["source_column"]
            return SQLBuilder.nearest_attribute(parcel_geom, f"{table}.{geom_col}", col).replace("{table}", table)

        if metric == "intersection_area_pct":
            return SQLBuilder.intersection_area_pct(parcel_geom, f"{table}.{geom_col}").replace("{table}", table)

        if metric == "nearest_boundary_distance":
            return SQLBuilder.nearest_boundary_distance(parcel_geom, f"{table}.{geom_col}").replace("{table}", table)

        raise ValueError(f"Unknown metric: {metric}")
