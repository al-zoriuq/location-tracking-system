import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

try:
    conexion = psycopg2.connect(
        host=os.getenv("rdshost"),
        port=5432,
        database=os.getenv("rdsdbname"),
        user=os.getenv("rdsuser"),
        password=os.getenv("rdspass"),
        sslmode="verify-full",
        sslrootcert="./global-bundle.pem"
    )

    print("CONEXIÓN A RDS EXITOSA")

    cursor = conexion.cursor()

    cursor.execute("SELECT version();")

    resultado = cursor.fetchone()

    print(resultado)

    cursor.close()
    conexion.close()

except Exception as e:
    print("ERROR:")
    print(e)