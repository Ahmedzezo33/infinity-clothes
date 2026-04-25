import cx_Oracle
DB_CONFIG = {
    'user': 'ahmed',
    'password': 'AHMEDX3COMai',
    'dsn': cx_Oracle.makedsn("localhost", 1521, service_name="ORCLPDB")
}