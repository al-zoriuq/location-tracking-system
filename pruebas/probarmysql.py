import mysql.connector

conexion = mysql.connector.connect(
    host="localhost",
    port=3306,
    user="root",
    password="example",
    database="p1dbdiseno"
)

if conexion.is_connected():
    print("Conectado a MySQL")

conexion.close()