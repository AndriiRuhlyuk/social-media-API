from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Add database indexes to OutstandingToken for better performance"

    def handle(self, *args, **options):
        table_name = "token_blacklist_outstandingtoken"

        self.stdout.write(f"Working with table: {table_name}")

        with connection.cursor() as cursor:
            self._create_expires_at_index(cursor, table_name)
            self._create_composite_index(cursor, table_name)

        self.stdout.write(self.style.SUCCESS("Index creation completed!"))

    def _create_expires_at_index(self, cursor, table_name):
        """Create index for expires_at"""
        try:
            sql = f"CREATE INDEX IF NOT EXISTS idx_outstanding_token_expires_at ON {table_name} (expires_at)"
            cursor.execute(sql)
            self.stdout.write(self.style.SUCCESS("Created index on expires_at"))
        except Exception as e:
            if "already exists" in str(e).lower():
                self.stdout.write(
                    self.style.WARNING("Index on expires_at already exists")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"Error creating expires_at index: {e}")
                )

    def _create_composite_index(self, cursor, table_name):
        """Create compose index for (user_id, expires_at)"""
        try:
            sql = f"CREATE INDEX IF NOT EXISTS idx_outstanding_token_user_expires ON {table_name} (user_id, expires_at)"
            cursor.execute(sql)
            self.stdout.write(
                self.style.SUCCESS("Created composite index on (user_id, expires_at)")
            )
        except Exception as e:
            if "already exists" in str(e).lower():
                self.stdout.write(self.style.WARNING("Composite index already exists"))
            else:
                self.stdout.write(
                    self.style.ERROR(f"Error creating composite index: {e}")
                )
