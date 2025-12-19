from django.db import connection

class ParcelFactsUpdater:

    def update_field(self, target_model, parcel_id, field, sql_fragment):
        table = target_model._meta.db_table

        full_sql = f"""
        UPDATE {table}
        SET {field} = ({sql_fragment})
        WHERE parcel_id = %s;
        """

        with connection.cursor() as cur:
            cur.execute(full_sql, [parcel_id])
