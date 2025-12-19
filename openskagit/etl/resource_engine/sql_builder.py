class SQLBuilder:

    # ---------------------------------------
    # Boolean intersects
    # ---------------------------------------
    @staticmethod
    def intersects_boolean(parcel_geom, table_geom):
        return f"ST_Intersects({parcel_geom}, {table_geom})"

    # ---------------------------------------
    # Intersects attribute
    # ---------------------------------------
    @staticmethod
    def intersects_attribute(parcel_geom, table_geom, col):
        return f"""
        (
            SELECT {col}
            FROM {{table}}
            WHERE ST_Intersects({parcel_geom}, {table_geom})
            LIMIT 1
        )
        """

    # ---------------------------------------
    # Nearest distance
    # ---------------------------------------
    @staticmethod
    def nearest_distance(parcel_geom, table_geom):
        return f"""
        (
            SELECT ST_Distance({parcel_geom}, {table_geom})
            FROM {{table}}
            ORDER BY {parcel_geom} <-> {table_geom}
            LIMIT 1
        )
        """

    # ---------------------------------------
    # Nearest attribute
    # ---------------------------------------
    @staticmethod
    def nearest_attribute(parcel_geom, table_geom, col):
        return f"""
        (
            SELECT {col}
            FROM {{table}}
            ORDER BY {parcel_geom} <-> {table_geom}
            LIMIT 1
        )
        """

    # ---------------------------------------
    # Intersection area percentage
    # ---------------------------------------
    @staticmethod
    def intersection_area_pct(parcel_geom, table_geom):
        return f"""
        (
            SELECT 
            ST_Area(ST_Intersection({parcel_geom}, {table_geom})) /
            NULLIF(ST_Area({parcel_geom}), 0)
            FROM {{table}}
            WHERE ST_Intersects({parcel_geom}, {table_geom})
            LIMIT 1
        )
        """

    # ---------------------------------------
    # Nearest boundary distance
    # ---------------------------------------
    @staticmethod
    def nearest_boundary_distance(parcel_geom, table_geom):
        return f"""
        (
            SELECT ST_Distance({parcel_geom}, {table_geom})
            FROM {{table}}
            ORDER BY {parcel_geom} <-> {table_geom}
            LIMIT 1
        )
        """
