import logging

from sqlalchemy import text, inspect

logger = logging.getLogger(__name__)


def get_sqlite_column_type(sqlalchemy_type):
    """Convert SQLAlchemy column type to SQLite type string."""
    type_str = str(sqlalchemy_type).lower()

    if "integer" in type_str or "int" in type_str:
        return "INTEGER"
    elif "text" in type_str:
        return "TEXT"
    elif "real" in type_str or "float" in type_str or "numeric" in type_str:
        return "REAL"
    elif "blob" in type_str:
        return "BLOB"
    elif "varchar" in type_str or "string" in type_str:
        return "TEXT"
    elif "datetime" in type_str:
        return "TIMESTAMP"
    elif "date" in type_str:
        return "DATE"
    elif "boolean" in type_str or "bool" in type_str:
        return "INTEGER"
    else:
        return "TEXT"


def migrate_database(app):
    """Automatically add missing columns to existing tables."""
    from database import db, Folder, PDFFile, Task, Settings

    with app.app_context():
        try:
            inspector = inspect(db.engine)
        except Exception as e:
            logger.warning(f"Failed to create inspector: {e}")
            return

        models = [
            ("folder", Folder),
            ("pdf_file", PDFFile),
            ("task", Task),
            ("settings", Settings),
        ]

        for table_name, model_class in models:
            try:
                _migrate_table_columns(table_name, model_class, inspector)
            except Exception as e:
                logger.warning(f"Migration failed for table '{table_name}': {e}")

        logger.info("Database migration completed")


def _migrate_table_columns(table_name, model_class, inspector):
    """Add missing columns to a table."""

    try:
        existing_columns = _get_existing_columns(inspector, table_name)
    except Exception as e:
        logger.warning(f"Could not inspect table '{table_name}': {e}")
        return

    model_columns = {col.name: col for col in model_class.__table__.columns}

    added_columns = 0

    for col_name, column in model_columns.items():
        if col_name not in existing_columns:
            try:
                sqlite_type = get_sqlite_column_type(column.type)
                nullable = "NOT NULL" if not column.nullable else "NULL"
                default = ""
                if column.default is not None and hasattr(column.default, "arg"):
                    default_str = str(column.default.arg)
                    if default_str and default_str != "None":
                        default = f" DEFAULT {default_str}"

                sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {sqlite_type} {nullable}{default}"

                with db.engine.begin() as conn:
                    conn.execute(text(sql))

                logger.info(
                    f"Migrated: Added column '{col_name}' to table '{table_name}'"
                )
                added_columns += 1
            except Exception as e:
                logger.warning(
                    f"Failed to add column '{col_name}' to table '{table_name}': {e}"
                )

    if added_columns > 0:
        logger.info(f"Table '{table_name}': Added {added_columns} columns")


def _get_existing_columns(inspector, table_name):
    """Get set of existing column names for a table."""
    try:
        columns = inspector.get_columns(table_name)
        return {col["name"] for col in columns}
    except Exception:
        return set()
