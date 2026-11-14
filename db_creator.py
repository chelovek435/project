import sqlite3 as sl
import csv
import sys
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QApplication
import openpyxl as op

new_filename = 'data.db'


def main(new_fname: str):
    fname = QFileDialog.getOpenFileName(
        None, 'Открыть файл', '', 'CSV (*.csv);;EXCEL (*.xlsx)')[0]
    if not fname:
        return
    try:
        with sl.connect(new_fname) as con:
            cur = con.cursor()
            cur.executescript('''
                CREATE TABLE IF NOT EXISTS cities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    lat REAL,
                    lon REAL
                );
                CREATE TABLE IF NOT EXISTS attractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    image_name TEXT,
                    lat REAL,
                    lon REAL,
                    FOREIGN KEY (city_id)
                    REFERENCES cities(id) ON DELETE CASCADE
                );
            ''')
            if fname.endswith('.xlsx'):
                import_from_excel(fname, cur)
            else:
                import_from_csv(fname, cur)

            con.commit()
            QMessageBox.information(None, 'Успех', 'Данные импортированы!')
    except Exception as e:
        QMessageBox.critical(
                None, 'Ошибка', f'Не удалось импортировать:\n{e}'
            )


def save_to_db(cur: sl.Cursor, row: list):
    # если данных не хватает они станут None
    city_name, name, desc, image, lat, lon = (row + (None,)*6)[:6]

    if not city_name or not name:
        return

    lat = float(lat) if lat is not None and str(lat).strip() != '' else None
    lon = float(lon) if lon is not None and str(lon).strip() != '' else None

    desc = str(desc) if desc is not None else ''
    image = str(image) if image is not None else ''

    cur.execute('INSERT OR IGNORE INTO cities (name) VALUES (?)', (city_name,))
    cur.execute('''
        INSERT INTO
        attractions (city_id, name, description, image_name, lat, lon)
        VALUES ((SELECT id FROM cities WHERE name = ?), ?, ?, ?, ?, ?)
    ''', (city_name, name, desc, image, lat, lon))


def import_from_excel(fname: str, cur: sl.Cursor):
    wb = op.load_workbook(fname, read_only=True)
    ws = wb.active
    for row in ws.iter_rows(min_row=2, values_only=True):
        save_to_db(cur, row)

    wb.close()


def import_from_csv(fname: str, cur: sl.Cursor):
    with open(fname, encoding='utf-8') as f:
        for row in csv.reader(f, delimiter=';'):
            save_to_db(cur, row)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main(new_filename)
