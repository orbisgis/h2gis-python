"""
* H2GIS-python is a Python wrapper to use H2GIS.
* <a href="http://www.h2database.com">http://www.h2database.com</a>. H2GIS-python is developed by CNRS
* <a href="http://www.cnrs.fr/">http://www.cnrs.fr/</a>.
*
* This code is part of the H2GIS-python project. H2GIS-python is free software;
* you can redistribute it and/or modify it under the terms of the GNU
* Lesser General Public License as published by the Free Software Foundation;
* version 3.0 of the License.
*
* H2GIS-python is distributed in the hope that it will be useful, but
* WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
* FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License
* for more details <http://www.gnu.org/licenses/>.
*
*
* For more information, please consult: <a href="http://www.h2gis.org/">http://www.h2gis.org/</a>
* or contact directly: info_at_h2gis.org

@author Maël PHILIPPE
@author Erwan BOCHER
"""

import unittest
from unittest.mock import MagicMock, patch
import ctypes

from h2gis import H2GIS  # Adjust import path as needed


class TestH2GIS(unittest.TestCase):

    def setUp(self):
        # Patch ctypes.CDLL in the h2gis module to mock native library
        patcher = patch('h2gis.h2gis.ctypes.CDLL')
        self.addCleanup(patcher.stop)
        self.mock_cdll = patcher.start()

        self.mock_lib = MagicMock()
        self.mock_cdll.return_value = self.mock_lib

        # Simulate isolate creation success
        self.mock_lib.graal_create_isolate.return_value = 0
        # Simulate a valid connection id
        self.mock_lib.h2gis_connect.return_value = 1234

        # Instantiate H2GIS, which will load the mock lib
        self.h2gis = H2GIS(lib_path="/user/home")
        self.h2gis.thread = ctypes.c_void_p(1234)  # Use 1234 as dummy thread pointer for tests
        self.h2gis.connection = 1234  # Set valid connection id by default for tests


    # ----- H2GIS() tests -----

    def test_init_default(self):
        # graal_create_isolate should be called with default lib path and succeed
        self.mock_lib.graal_create_isolate.return_value = 0
        self.mock_lib.graal_create_isolate.reset_mock()

        instance = H2GIS(lib_path="/user/home")  # lib_path given to avoid path logic
        self.assertEqual(instance.connection, 0)
        self.mock_lib.graal_create_isolate.assert_called_once()

    def test_init_custom_lib_path(self):
        custom_path = "custom/path/libh2gis.so"
        H2GIS(lib_path=custom_path)
        self.mock_cdll.assert_called_with(custom_path)

    def test_init_error_on_isolate_failure(self):
        self.mock_lib.graal_create_isolate.return_value = -1
        with self.assertRaises(RuntimeError) as cm:
            self.mock_lib.graal_create_isolate.reset_mock()
            H2GIS(lib_path="/user/home")
        self.assertIn("Failed to create GraalVM isolate", str(cm.exception))

    @patch.object(H2GIS, 'connect')
    def test_init_with_dbpath_calls_connect(self, mock_connect):
        self.mock_lib.graal_create_isolate.reset_mock()
        H2GIS(lib_path="/user/home", dbPath="test.mv.db")
        mock_connect.assert_called_once_with("test.mv.db", "sa", "")

    @patch.object(H2GIS, 'connect')
    def test_init_with_dbpath_and_credentials(self, mock_connect):
        self.mock_lib.graal_create_isolate.reset_mock()
        H2GIS(lib_path="/user/home", dbPath="test.mv.db", username="admin", password="secret")
        mock_connect.assert_called_once_with("test.mv.db", "admin", "secret")


    # ----- connect() tests -----

    def test_connect_normal_case(self):
        self.h2gis.connect("testdb.mv.db")
        self.mock_lib.h2gis_connect.assert_called_with(
            self.h2gis.thread,
            b"testdb.mv.db",
            b"sa",
            b""
        )
        self.assertEqual(self.h2gis.connection, 1234)

    def test_connect_with_custom_credentials(self):
        self.h2gis.connect("testdb.mv.db", username="admin", password="secret")
        self.mock_lib.h2gis_connect.assert_called_with(
            self.h2gis.thread,
            b"testdb.mv.db",
            b"admin",
            b"secret"
        )

    def test_connect_limit_case_long_filename(self):
        long_name = "a" * 255 + ".mv.db"
        self.h2gis.connect(long_name)
        self.mock_lib.h2gis_connect.assert_called_with(
            self.h2gis.thread,
            long_name.encode("utf-8"),
            b"sa",
            b""
        )

    def test_connect_error_connection_failed(self):
        self.mock_lib.h2gis_connect.return_value = 0  # simulate failure
        with self.assertRaises(RuntimeError) as cm:
            self.h2gis.connect("invalid.mv.db")
        self.assertIn("Failed to connect", str(cm.exception))

    def test_connect_empty_filename(self):
        self.mock_lib.h2gis_connect.return_value = 0
        with self.assertRaises(RuntimeError):
            self.h2gis.connect("")

    def test_connect_null_params(self):
        # Your H2GIS connect method should raise ValueError or TypeError for None parameters
        with self.assertRaises(ValueError):
            self.h2gis.connect(None, None, None)

    # ----- execute() tests -----

    def test_execute_normal(self):
        self.mock_lib.h2gis_execute_update.return_value = 5
        affected = self.h2gis.execute("UPDATE table SET col = 1")
        self.mock_lib.h2gis_execute_update.assert_called_once_with(
            self.h2gis.thread,
            self.h2gis.connection,
            b"UPDATE table SET col = 1"
        )
        self.assertEqual(affected, 5)

    def test_execute_limit_large_query(self):
        long_sql = "UPDATE table SET col = 'x'" * 1000
        self.mock_lib.h2gis_execute_update.return_value = 1
        affected = self.h2gis.execute(long_sql)
        self.mock_lib.h2gis_execute_update.assert_called_once()
        self.assertEqual(affected, 1)

    def test_execute_error_invalid_connection(self):
        self.h2gis.connection = 0  # invalid connection
        self.mock_lib.h2gis_execute_update.return_value = -1
        affected = self.h2gis.execute("DELETE FROM table")
        self.assertEqual(affected, -1)

    # ----- fetch() tests -----

    def test_fetch_normal(self):
        self.mock_lib.h2gis_execute.return_value = 5678
        self.mock_lib.h2gis_fetch_row.side_effect = [
            b"row1_data",
            b"row2_data",
            b"row3_data",
            None
        ]

        rows = self.h2gis.fetch("SELECT * FROM table")
        self.mock_lib.h2gis_execute.assert_called_once_with(
            self.h2gis.thread,
            self.h2gis.connection,
            b"SELECT * FROM table"
        )
        self.assertEqual(rows, ["row1_data", "row2_data", "row3_data"])
        self.mock_lib.h2gis_close_query.assert_called_once_with(self.h2gis.thread, 5678)

    def test_fetch_limit_empty_result(self):
        self.mock_lib.h2gis_execute.return_value = 123
        self.mock_lib.h2gis_fetch_row.return_value = None

        rows = self.h2gis.fetch("SELECT * FROM empty_table")
        self.assertEqual(rows, [])
        self.mock_lib.h2gis_close_query.assert_called_once_with(self.h2gis.thread, 123)

    def test_fetch_error_query_failed(self):
        self.mock_lib.h2gis_execute.return_value = 0
        with self.assertRaises(RuntimeError) as cm:
            self.h2gis.fetch("SELECT * FROM invalid_table")
        self.assertIn("Query execution failed", str(cm.exception))

    def test_fetch_error_fetch_row_failure(self):
        self.mock_lib.h2gis_execute.return_value = 789
        self.mock_lib.h2gis_fetch_row.side_effect = [b"valid_row", None]

        rows = self.h2gis.fetch("SELECT * FROM table")
        self.assertEqual(rows, ["valid_row"])
        self.mock_lib.h2gis_close_query.assert_called_once_with(self.h2gis.thread, 789)

    def test_fetch_error_invalid_sql(self):
        self.mock_lib.h2gis_execute.return_value = 0
        with self.assertRaises(RuntimeError):
            self.h2gis.fetch("INVALID SQL")

    # ----- close() tests -----

    def test_close_connection_open(self):
        self.h2gis.connection = 1234
        self.h2gis.close()
        self.mock_lib.h2gis_close_connection.assert_called_once_with(
            self.h2gis.thread, 1234
        )
        self.assertEqual(self.h2gis.connection, 0)

    def test_close_connection_already_closed(self):
        self.h2gis.connection = 0
        self.h2gis.close()
        self.mock_lib.h2gis_close_connection.assert_not_called()
        self.assertEqual(self.h2gis.connection, 0)

    # ----- deleteDatabase() tests -----

    def test_delete_database_connection_open(self):
        self.h2gis.connection = 1234
        self.h2gis.deleteDatabase()
        self.mock_lib.h2gis_delete_database_and_close.assert_called_once_with(
            self.h2gis.thread, 1234
        )
        self.assertEqual(self.h2gis.connection, 0)

    def test_delete_database_connection_already_closed(self):
        self.h2gis.connection = 0
        self.h2gis.deleteDatabase()
        self.mock_lib.h2gis_delete_database_and_close.assert_not_called()
        self.assertEqual(self.h2gis.connection, 0)



if __name__ == '__main__':
    unittest.main()
