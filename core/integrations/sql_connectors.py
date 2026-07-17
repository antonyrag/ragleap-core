"""
MySQL and PostgreSQL connectors for RagLeap Core integrations.
Ported from production's api/addon_services.py — logic unchanged,
only the makerag_* required-table names renamed to ragleap_*.
"""
import re
import json
import logging
from typing import Dict, Any, Tuple, List, Optional

from core.integrations.base import BaseDatabaseConnector

logger = logging.getLogger(__name__)


class MySQLConnector(BaseDatabaseConnector):
    """MySQL database connector"""

    def test_connection(self) -> Tuple[bool, str]:
        try:
            import pymysql

            conn_string = self.data_source.connection_string
            pattern = r'mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
            match = re.match(pattern, conn_string)

            if not match:
                return False, "Invalid connection string format"

            user, password, host, port, database = match.groups()

            connection = pymysql.connect(
                host=host, port=int(port), user=user, password=password,
                database=database, connect_timeout=10
            )
            connection.close()

            return True, "Connection successful"
        except ImportError:
            return False, "pymysql not installed. Run: pip install pymysql"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            import pymysql

            conn_string = self.data_source.connection_string
            pattern = r'mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
            match = re.match(pattern, conn_string)

            if not match:
                raise ValueError("Invalid connection string format")

            user, password, host, port, database = match.groups()

            connection = pymysql.connect(
                host=host, port=int(port), user=user, password=password,
                database=database, cursorclass=pymysql.cursors.DictCursor
            )

            try:
                with connection.cursor() as cursor:
                    query = self.data_source.query_template
                    params = []

                    if user_identifier:
                        query = query.replace('{{user_id}}', '%s')
                        query = query.replace('{{user_identifier}}', '%s')
                        params = [user_identifier] * query.count('%s')

                    cursor.execute(query, params if params else None)
                    results = cursor.fetchall()

                    mapped_results = []
                    for row in results:
                        mapped_row = self._apply_field_mappings(row)
                        mapped_results.append(mapped_row)

                    return mapped_results
            finally:
                connection.close()

        except Exception as e:
            logger.error(f"MySQL fetch error: {e}")
            raise

    def _apply_field_mappings(self, row: Dict) -> Dict:
        mappings = self.data_source.field_mappings
        if not mappings:
            return row

        result = {}
        for source_field, target_field in mappings.items():
            if source_field in row:
                result[target_field] = row[source_field]

        for key, value in row.items():
            if key not in mappings:
                result[key] = value

        return result

    def introspect_schema(self) -> Dict[str, Any]:
        try:
            import pymysql

            conn_string = self.data_source.connection_string
            pattern = r'mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
            match = re.match(pattern, conn_string)
            if not match:
                return {'tables': [], 'error': 'Invalid connection string format'}

            user, password, host, port, database = match.groups()
            connection = pymysql.connect(
                host=host, port=int(port), user=user, password=password,
                database=database, cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=10
            )

            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    all_tables = [list(row.values())[0] for row in cursor.fetchall()]

                    allowed_tables = []
                    filtered_count = 0

                    for table in all_tables:
                        if self._is_table_blacklisted(table):
                            filtered_count += 1
                            continue

                        cursor.execute(f"DESCRIBE `{table}`")
                        columns = []
                        for col in cursor.fetchall():
                            col_name = col.get('Field', '')
                            columns.append({
                                'name': col_name,
                                'type': col.get('Type', ''),
                                'nullable': col.get('Null', '') == 'YES',
                                'is_key': col.get('Key', '') == 'PRI',
                                'is_sensitive': self._is_column_sensitive(col_name),
                            })

                        allowed_tables.append({
                            'name': table,
                            'columns': columns,
                            'column_count': len(columns),
                        })

                    return {
                        'tables': allowed_tables,
                        'total_tables': len(all_tables),
                        'allowed_tables': len(allowed_tables),
                        'filtered_count': filtered_count,
                        'database': database,
                        'db_type': 'mysql',
                    }
            finally:
                connection.close()
        except Exception as e:
            logger.error(f"MySQL schema introspection error: {e}")
            return {'tables': [], 'error': str(e)}

    def _parse_mysql_conn(self):
        conn_string = self.data_source.connection_string
        pattern = r'mysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
        match = re.match(pattern, conn_string)
        if not match:
            return None
        user, password, host, port, database = match.groups()
        return {'user': user, 'password': password, 'host': host, 'port': int(port), 'database': database}

    def check_required_schema(self) -> Dict[str, Any]:
        try:
            import pymysql

            params = self._parse_mysql_conn()
            if not params:
                return {'supported': True, 'error': 'Invalid connection string format'}

            connection = pymysql.connect(
                host=params['host'], port=params['port'],
                user=params['user'], password=params['password'],
                database=params['database'], connect_timeout=10,
            )
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    existing = {list(row)[0] for row in cursor.fetchall()}

                    tables = {}
                    for tbl in self.REQUIRED_TABLES:
                        tables[tbl] = {
                            'exists': tbl in existing,
                            'status': 'ready' if tbl in existing else 'missing',
                            'description': self.REQUIRED_TABLES[tbl]['description'],
                            'columns': self.REQUIRED_TABLES[tbl]['columns'],
                        }

                    return {
                        'supported': True,
                        'tables': tables,
                        'all_ready': all(t['exists'] for t in tables.values()),
                        'missing_count': sum(1 for t in tables.values() if not t['exists']),
                        'has_pgvector': False,
                        'db_type': 'mysql',
                    }
            finally:
                connection.close()
        except ImportError:
            return {'supported': False, 'message': 'pymysql not installed'}
        except Exception as e:
            logger.error(f"MySQL schema check error: {e}")
            return {'supported': True, 'tables': {}, 'error': str(e)}

    def create_required_schema(self) -> Dict[str, Any]:
        try:
            import pymysql

            params = self._parse_mysql_conn()
            if not params:
                return {'supported': True, 'success': False, 'error': 'Invalid connection string format'}

            connection = pymysql.connect(
                host=params['host'], port=params['port'],
                user=params['user'], password=params['password'],
                database=params['database'], connect_timeout=15,
                autocommit=False,
            )
            created = []
            skipped = []
            errors = []

            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW TABLES")
                    existing = {list(row)[0] for row in cursor.fetchall()}

                    if 'ragleap_documents' in existing:
                        skipped.append('ragleap_documents')
                    else:
                        try:
                            cursor.execute("""
                                CREATE TABLE ragleap_documents (
                                    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
                                    source_id TEXT,
                                    title TEXT,
                                    content LONGTEXT,
                                    metadata JSON,
                                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                    INDEX idx_rl_docs_source (source_id(255)),
                                    INDEX idx_rl_docs_created (created_at)
                                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                            """)
                            connection.commit()
                            created.append('ragleap_documents')
                        except Exception as e:
                            connection.rollback()
                            errors.append({'table': 'ragleap_documents', 'error': str(e)})

                    if 'ragleap_chunks' in existing:
                        skipped.append('ragleap_chunks')
                    else:
                        try:
                            cursor.execute("""
                                CREATE TABLE ragleap_chunks (
                                    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
                                    document_id CHAR(36),
                                    chunk_text LONGTEXT,
                                    chunk_index INT,
                                    metadata JSON,
                                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                    INDEX idx_rl_chunks_doc (document_id),
                                    INDEX idx_rl_chunks_idx (chunk_index),
                                    FOREIGN KEY (document_id) REFERENCES ragleap_documents(id) ON DELETE CASCADE
                                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                            """)
                            connection.commit()
                            created.append('ragleap_chunks')
                        except Exception as e:
                            connection.rollback()
                            errors.append({'table': 'ragleap_chunks', 'error': str(e)})

                    if 'ragleap_embeddings' in existing:
                        skipped.append('ragleap_embeddings')
                    else:
                        try:
                            cursor.execute("""
                                CREATE TABLE ragleap_embeddings (
                                    id CHAR(36) PRIMARY KEY DEFAULT (UUID()),
                                    chunk_id CHAR(36),
                                    embedding JSON,
                                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                    INDEX idx_rl_embed_chunk (chunk_id),
                                    FOREIGN KEY (chunk_id) REFERENCES ragleap_chunks(id) ON DELETE CASCADE
                                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                            """)
                            connection.commit()
                            created.append('ragleap_embeddings')
                        except Exception as e:
                            connection.rollback()
                            errors.append({'table': 'ragleap_embeddings', 'error': str(e)})

                return {
                    'supported': True,
                    'created': created,
                    'skipped': skipped,
                    'errors': errors,
                    'success': len(errors) == 0,
                    'has_pgvector': False,
                    'db_type': 'mysql',
                }
            finally:
                connection.close()
        except ImportError:
            return {'supported': False, 'message': 'pymysql not installed'}
        except Exception as e:
            logger.error(f"MySQL schema creation error: {e}")
            return {'supported': True, 'success': False, 'error': str(e)}

    def insert_document(self, table_name: str, title: str, content: str,
                        metadata: Optional[Dict] = None, source_type: str = 'upload') -> Dict[str, Any]:
        try:
            import pymysql

            params = self._parse_mysql_conn()
            if not params:
                return {'success': False, 'error': 'Invalid connection string format'}

            connection = pymysql.connect(
                host=params['host'], port=params['port'],
                user=params['user'], password=params['password'],
                database=params['database'], connect_timeout=10,
                autocommit=False,
            )
            try:
                with connection.cursor() as cursor:
                    import uuid
                    doc_id = str(uuid.uuid4())
                    meta_json = json.dumps(metadata or {})
                    cursor.execute(
                        f"INSERT INTO `{table_name}` (id, title, content, metadata, source_type, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, NOW())",
                        (doc_id, title, content, meta_json, source_type),
                    )
                    connection.commit()
                    return {'success': True, 'id': doc_id}
            finally:
                connection.close()
        except Exception as e:
            logger.error(f"MySQL insert_document error: {e}")
            return {'success': False, 'error': str(e)}


class PostgreSQLConnector(BaseDatabaseConnector):
    """PostgreSQL database connector"""

    def test_connection(self) -> Tuple[bool, str]:
        try:
            import psycopg2

            conn_string = self.data_source.connection_string
            connection = psycopg2.connect(conn_string, connect_timeout=10)
            connection.close()

            return True, "Connection successful"
        except ImportError:
            return False, "psycopg2 not installed. Run: pip install psycopg2-binary"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def fetch_data(self, user_identifier: str = None) -> List[Dict]:
        try:
            import psycopg2
            import psycopg2.extras

            connection = psycopg2.connect(self.data_source.connection_string)

            try:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    query = self.data_source.query_template
                    params = []

                    if user_identifier:
                        query = query.replace('{{user_id}}', '%s')
                        query = query.replace('{{user_identifier}}', '%s')
                        params = [user_identifier] * query.count('%s')

                    cursor.execute(query, params if params else None)
                    results = cursor.fetchall()

                    return [dict(row) for row in results]
            finally:
                connection.close()

        except Exception as e:
            logger.error(f"PostgreSQL fetch error: {e}")
            raise

    def introspect_schema(self) -> Dict[str, Any]:
        try:
            import psycopg2
            import psycopg2.extras

            connection = psycopg2.connect(self.data_source.connection_string, connect_timeout=10)

            try:
                with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute("""
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_type = 'BASE TABLE'
                        ORDER BY table_name
                    """)
                    all_tables = [row['table_name'] for row in cursor.fetchall()]

                    allowed_tables = []
                    filtered_count = 0

                    for table in all_tables:
                        if self._is_table_blacklisted(table):
                            filtered_count += 1
                            continue

                        cursor.execute("""
                            SELECT column_name, data_type, is_nullable,
                                   column_default, character_maximum_length
                            FROM information_schema.columns
                            WHERE table_schema = 'public' AND table_name = %s
                            ORDER BY ordinal_position
                        """, (table,))

                        columns = []
                        for col in cursor.fetchall():
                            col_name = col['column_name']
                            col_type = col['data_type']
                            if col.get('character_maximum_length'):
                                col_type += f"({col['character_maximum_length']})"
                            columns.append({
                                'name': col_name,
                                'type': col_type,
                                'nullable': col['is_nullable'] == 'YES',
                                'has_default': col['column_default'] is not None,
                                'is_sensitive': self._is_column_sensitive(col_name),
                            })

                        cursor.execute("""
                            SELECT kcu.column_name
                            FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage kcu
                                ON tc.constraint_name = kcu.constraint_name
                            WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
                        """, (table,))
                        pk_cols = {row['column_name'] for row in cursor.fetchall()}
                        for col in columns:
                            col['is_key'] = col['name'] in pk_cols

                        allowed_tables.append({
                            'name': table,
                            'columns': columns,
                            'column_count': len(columns),
                        })

                    db_name = ''
                    try:
                        m = re.search(r'/([^/?]+)(\?|$)', self.data_source.connection_string)
                        if m:
                            db_name = m.group(1)
                    except Exception:
                        pass

                    return {
                        'tables': allowed_tables,
                        'total_tables': len(all_tables),
                        'allowed_tables': len(allowed_tables),
                        'filtered_count': filtered_count,
                        'database': db_name,
                        'db_type': 'postgresql',
                    }
            finally:
                connection.close()
        except Exception as e:
            logger.error(f"PostgreSQL schema introspection error: {e}")
            return {'tables': [], 'error': str(e)}

    def check_required_schema(self) -> Dict[str, Any]:
        try:
            import psycopg2

            required = list(self.REQUIRED_TABLES.keys())
            connection = psycopg2.connect(self.data_source.connection_string, connect_timeout=10)
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT table_name FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = ANY(%s)
                    """, (required,))
                    existing = {row[0] for row in cursor.fetchall()}

                    cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
                    has_pgvector = cursor.fetchone() is not None

                    tables = {}
                    for tbl in required:
                        tables[tbl] = {
                            'exists': tbl in existing,
                            'status': 'ready' if tbl in existing else 'missing',
                            'description': self.REQUIRED_TABLES[tbl]['description'],
                            'columns': self.REQUIRED_TABLES[tbl]['columns'],
                        }

                    return {
                        'supported': True,
                        'tables': tables,
                        'all_ready': all(t['exists'] for t in tables.values()),
                        'missing_count': sum(1 for t in tables.values() if not t['exists']),
                        'has_pgvector': has_pgvector,
                        'db_type': 'postgresql',
                    }
            finally:
                connection.close()
        except ImportError:
            return {'supported': False, 'message': 'psycopg2 not installed'}
        except Exception as e:
            logger.error(f"PostgreSQL schema check error: {e}")
            return {'supported': True, 'tables': {}, 'error': str(e)}

    def create_required_schema(self) -> Dict[str, Any]:
        try:
            import psycopg2

            connection = psycopg2.connect(self.data_source.connection_string, connect_timeout=15)
            created = []
            skipped = []
            errors = []

            try:
                has_pgvector = False
                try:
                    connection.autocommit = True
                    with connection.cursor() as cursor:
                        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    has_pgvector = True
                except Exception as ext_err:
                    logger.info(f"pgvector extension not available: {ext_err}")
                finally:
                    connection.autocommit = False

                with connection.cursor() as cursor:
                    try:
                        cursor.execute("""
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = 'ragleap_documents'
                        """)
                        if cursor.fetchone():
                            skipped.append('ragleap_documents')
                        else:
                            cursor.execute("""
                                CREATE TABLE ragleap_documents (
                                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                                    source_id TEXT,
                                    title TEXT,
                                    content TEXT,
                                    metadata JSONB DEFAULT '{}',
                                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                                )
                            """)
                            cursor.execute("CREATE INDEX idx_rl_docs_source ON ragleap_documents(source_id)")
                            cursor.execute("CREATE INDEX idx_rl_docs_created ON ragleap_documents(created_at)")
                            connection.commit()
                            created.append('ragleap_documents')
                    except Exception as e:
                        connection.rollback()
                        errors.append({'table': 'ragleap_documents', 'error': str(e)})

                    try:
                        cursor.execute("""
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = 'ragleap_chunks'
                        """)
                        if cursor.fetchone():
                            skipped.append('ragleap_chunks')
                        else:
                            cursor.execute("""
                                CREATE TABLE ragleap_chunks (
                                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                                    document_id UUID REFERENCES ragleap_documents(id) ON DELETE CASCADE,
                                    chunk_text TEXT,
                                    chunk_index INTEGER,
                                    metadata JSONB DEFAULT '{}',
                                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                                )
                            """)
                            cursor.execute("CREATE INDEX idx_rl_chunks_doc ON ragleap_chunks(document_id)")
                            cursor.execute("CREATE INDEX idx_rl_chunks_idx ON ragleap_chunks(chunk_index)")
                            connection.commit()
                            created.append('ragleap_chunks')
                    except Exception as e:
                        connection.rollback()
                        errors.append({'table': 'ragleap_chunks', 'error': str(e)})

                    try:
                        cursor.execute("""
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = 'public' AND table_name = 'ragleap_embeddings'
                        """)
                        if cursor.fetchone():
                            skipped.append('ragleap_embeddings')
                        else:
                            if has_pgvector:
                                cursor.execute("""
                                    CREATE TABLE ragleap_embeddings (
                                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                                        chunk_id UUID REFERENCES ragleap_chunks(id) ON DELETE CASCADE,
                                        embedding vector(3072),
                                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                                    )
                                """)
                                cursor.execute("""
                                    CREATE INDEX idx_rl_embed_vec
                                    ON ragleap_embeddings
                                    USING hnsw (embedding vector_cosine_ops)
                                """)
                            else:
                                cursor.execute("""
                                    CREATE TABLE ragleap_embeddings (
                                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                                        chunk_id UUID REFERENCES ragleap_chunks(id) ON DELETE CASCADE,
                                        embedding JSONB,
                                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                                    )
                                """)
                            cursor.execute("CREATE INDEX idx_rl_embed_chunk ON ragleap_embeddings(chunk_id)")
                            connection.commit()
                            created.append('ragleap_embeddings')
                    except Exception as e:
                        connection.rollback()
                        errors.append({'table': 'ragleap_embeddings', 'error': str(e)})

                return {
                    'supported': True,
                    'created': created,
                    'skipped': skipped,
                    'errors': errors,
                    'success': len(errors) == 0,
                    'has_pgvector': has_pgvector,
                    'db_type': 'postgresql',
                }
            finally:
                connection.close()
        except ImportError:
            return {'supported': False, 'message': 'psycopg2 not installed'}
        except Exception as e:
            logger.error(f"PostgreSQL schema creation error: {e}")
            return {'supported': True, 'success': False, 'error': str(e)}

    def insert_document(self, table_name: str, title: str, content: str,
                        metadata: Optional[Dict] = None, source_type: str = 'upload') -> Dict[str, Any]:
        try:
            import psycopg2

            connection = psycopg2.connect(self.data_source.connection_string, connect_timeout=10)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f'INSERT INTO "{table_name}" (title, content, metadata, created_at) '
                        "VALUES (%s, %s, %s, NOW()) RETURNING id",
                        (title, content, json.dumps(metadata or {})),
                    )
                    row = cursor.fetchone()
                    connection.commit()
                    doc_id = str(row[0]) if row else None
                    return {'success': True, 'id': doc_id}
            finally:
                connection.close()
        except Exception as e:
            logger.error(f"PostgreSQL insert_document error: {e}")
            return {'success': False, 'error': str(e)}
