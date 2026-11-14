import sys
import os
import shutil
import csv
import openpyxl as op
# import io
# from PyQt6 import uic
import sqlite3 as sl
from functools import wraps
from typing import Callable
from PyQt6.QtWidgets import (QApplication, QMainWindow, QTabWidget,
                             QTabBar, QInputDialog, QMessageBox,
                             QTableWidgetItem, QHeaderView, QAbstractItemView,
                             QDialog, QFileDialog, QLabel, QWidget,
                             QVBoxLayout, QCheckBox,
                             QGraphicsView, QGraphicsScene,
                             QGraphicsPixmapItem, QGraphicsEllipseItem,
                             QGraphicsSimpleTextItem, QGraphicsItem)
from PyQt6.QtCore import QObject, QEvent, Qt, QPointF
from PyQt6.QtGui import (QMouseEvent, QPixmap, QPainter, QPen, QBrush,
                         QShortcut, QKeySequence, QColor, QFont, QPalette)
from PyQt6.QtWidgets import QFrame

from UI.u import Ui_MainWindow
from UI.u2 import Ui_Dialog
from UI.u3 import Ui_Dialog as Ui_CityDialog

template = """"""
dev = True


class Map(QGraphicsView):
    LAT_TOP = 90.0
    LAT_BOTTOM = -90.0
    LON_LEFT = -180.0
    LON_RIGHT = 180.0

    def __init__(self, parent, map_path: str):
        super().__init__(parent)

        # создаем сцену
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # ставим на нее картинку карты
        self.pix = QPixmap(map_path)
        self.pix_item = QGraphicsPixmapItem(self.pix)
        self.scene.addItem(self.pix_item)

        # убираем белую рамку по краям чтоб карта сливалась с окном
        self.setFrameShape(QFrame.Shape.NoFrame)

        # Скрываем ползунки
        self.setStyleSheet("QScrollBar { width: 0px; height: 0px; }")

        # устанавливаем цвет фона окна
        self.setBackgroundBrush(QBrush(QColor("#cceeff")))
        # задаем сцене границы
        self.scene.setSceneRect(0, 0, self.pix.width(), self.pix.height())

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self.min_scale = 0.0
        self.cities = []
        self.attractions = []
        self.show_cities = True
        self.show_atrs = True
        self.marker_items = []
        self._user_zoomed = False

    def set_ct_and_atr(self, cities: list, attractions: list):
        self.cities = cities
        self.attractions = attractions
        self.redraw_markers()

    def set_layers(self, show_cities: bool, show_atrs: bool):
        self.show_cities = show_cities
        self.show_atrs = show_atrs
        self.redraw_markers()

    def _latlon_to_scene(self, lat: float, lon: float) -> QPointF | None:
        if lat is None or lon is None:
            return None

        x = (lon - self.LON_LEFT) / (
            self.LON_RIGHT - self.LON_LEFT) * self.pix.width()
        y = (self.LAT_TOP - lat) / (
            self.LAT_TOP - self.LAT_BOTTOM) * self.pix.height()
        return QPointF(x, y)

    def redraw_markers(self):
        for item in self.marker_items:
            self.scene.removeItem(item)
        self.marker_items.clear()

        if self.show_cities:
            for name, lat, lon in self.cities:
                pos = self._latlon_to_scene(lat, lon)
                if pos:
                    circle = QGraphicsEllipseItem(-12, -12, 24, 24)
                    circle.setFlag(
                        QGraphicsItem.GraphicsItemFlag.
                        ItemIgnoresTransformations)
                    circle.setBrush(QBrush(Qt.GlobalColor.blue))
                    circle.setPen(QPen(Qt.GlobalColor.darkBlue, 2))
                    circle.setZValue(10)
                    circle.setPos(pos)

                    # сохраняем информацию
                    circle.setData(0, "city")
                    circle.setData(1, name)

                    self.scene.addItem(circle)
                    self.marker_items.append(circle)

                    # Текст города
                    text = QGraphicsSimpleTextItem(name)
                    text.setParentItem(circle)

                    font = QFont("Arial", 11)
                    font.setBold(True)
                    text.setFont(font)

                    # отступ чтоб текст с меткой не сливался
                    text.setPos(16, -12)

        if self.show_atrs:
            for name, lat, lon in self.attractions:
                pos = self._latlon_to_scene(lat, lon)
                if pos:
                    # ДОСТОПРИМЕЧАТЕЛЬНОСТЬ: увеличили до 18x18 (было 12x12)
                    circle = QGraphicsEllipseItem(-9, -9, 18, 18)
                    circle.setFlag(
                        QGraphicsItem.GraphicsItemFlag.
                        ItemIgnoresTransformations)
                    circle.setBrush(QBrush(Qt.GlobalColor.red))
                    circle.setPen(QPen(Qt.GlobalColor.darkRed, 2))
                    circle.setZValue(5)
                    circle.setPos(pos)

                    # СОХРАНЯЕМ ИНФОРМАЦИЮ В МАРКЕР
                    circle.setData(0, "attraction")
                    circle.setData(1, name)

                    self.scene.addItem(circle)
                    self.marker_items.append(circle)

    def wheelEvent(self, event):
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
        else:
            zoom_factor = zoom_out_factor

        # Вычисляем масштаб, который ПОЛУЧИТСЯ после прокрутки
        new_scale = self.transform().m11() * zoom_factor

        # Считаем минимально возможный масштаб для текущего размера окна
        min_scale = max(
            self.viewport().width() / self.scene.sceneRect().width(),
            self.viewport().height() / self.scene.sceneRect().height()
        )

        # ограничиваем максимальное приближение
        max_scale = 4000.0
        if zoom_factor > 1 and new_scale >= max_scale:
            return

        # Если мы отдаляем карту и достигли предела — просто
        # ИГНОРИРУЕМ прокрутку
        if zoom_factor < 1 and new_scale <= min_scale:
            return  # <--- ВОТ ЗДЕСЬ. Никаких fitInView, просто стоп!

        # Если все ок — применяем зум
        self._user_zoomed = True
        self.scale(zoom_factor, zoom_factor)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        # Считаем минимальный масштаб для НОВОГО размера окна
        min_scale = max(
            self.viewport().width() / self.scene.sceneRect().width(),
            self.viewport().height() / self.scene.sceneRect().height()
        )

        # Если пользователь еще не трогал зум, вписываем карту
        if not self._user_zoomed:
            self.fitInView(
                self.scene.sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        else:
            # Если окно стало настолько большим, что текущий масштаб
            # уже не заполняет экран — принудительно увеличиваем карту
            current_scale = self.transform().m11()
            if current_scale < min_scale:
                self.fitInView(
                    self.scene.sceneRect(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding)


class TabFilter(QObject):
    '''создаем класс-фильтр'''

    def __init__(
            self, parent: "Project", tab_widget: QTabWidget, ind: int, pw: str
    ):
        super().__init__(parent)
        self.tab_widget = tab_widget
        self.ind = ind
        self.password = pw
        self.enabled = not dev

    def eventFilter(self, tab: QTabBar, event: QMouseEvent):
        # ловим клик
        if event.type() == QEvent.Type.MouseButtonPress:
            # получаем индекс нажатого виджета в баре
            clicked_ind = tab.tabAt(event.position().toPoint())

            if clicked_ind == self.ind and (
                self.ind != self.tab_widget.currentIndex()
            ):
                text = ''
                if self.enabled:
                    text, ok = QInputDialog.getText(
                        self.tab_widget, 'Авторизация', 'Введите пароль')
                else:
                    ok = True
                if ok:
                    if text == self.password or not self.enabled:
                        return False  # вкладка откроется
                    else:
                        QMessageBox.critical(
                            self.tab_widget, 'Ошибка', 'Неправильный пароль')
                return True  # клик игнорируется
        return super().eventFilter(tab, event)  # передача обработки дальше


class CityDialog(QDialog, Ui_CityDialog):
    def __init__(self, parent: "Project", mode='add'):
        super().__init__(parent)
        self.par = parent
        self.mode = mode
        self.setWindowTitle('Город')
        self.setupUi(self)
        self.initUI()

    def initUI(self):
        self.ok_btn.clicked.connect(self.check)
        self.cancel_btn.clicked.connect(self.reject)

        if self.mode == 'add':
            self.city_combo.hide()
            self.city_edit.show()
            self.label_3.setText('Введите название города:')
        else:
            self.city_combo.show()
            self.city_edit.hide()
            self.label_3.setText('Выберите город:')

            cities = [
                row[0] for row in self.par.fetch('SELECT name FROM cities')[0]]
            self.city_combo.addItems([''] + cities)

            self.city_combo.currentTextChanged.connect(self.city_changed)

    def city_changed(self, city_name: str):
        if not city_name:
            return
        row = self.par.fetch(
            'SELECT lat, lon FROM cities WHERE name = ?', (city_name,)
        )[0][0]
        if row:
            self.lat_edit.setText("" if row[0] is None else str(row[0]))
            self.lon_edit.setText("" if row[1] is None else str(row[1]))

    def check(self):
        if self.mode == 'add' and not self.city_edit.text().strip():
            QMessageBox.warning(self, 'Ошибка', 'Введите название города')
            return
        if self.mode == 'edit' and not self.city_combo.currentText():
            QMessageBox.warning(self, 'Ошибка', 'Выберите город')
            return

        if not self.par.valid_coord(self):
            return

        self.accept()

    def get_data(self) -> tuple[str, float, float]:
        lat_text = self.lat_edit.text().strip()
        lon_text = self.lon_edit.text().strip()

        lat = float(lat_text) if lat_text else None
        lon = float(lon_text) if lon_text else None

        return (
            self.city_edit.text().strip() if self.mode == 'add'
            else self.city_combo.currentText(),
            lat, lon
        )


class EditDialog(QDialog, Ui_Dialog):
    def __init__(
            self, parent: "Project", city='',
            name='', desc='', image='', lat='', lon='', redact=False
    ):
        super().__init__(parent)
        self.par = parent
        self.setWindowTitle('Редактирование достопримечательности')
        self.setupUi(self)

        self.city_combobox.addItems([''] + [
            i[0] for i in self.par.fetch(
                'SELECT name FROM cities')[0]])

        # подключаем кнопки
        self.ok.clicked.connect(self.check)
        self.cancel.clicked.connect(self.reject)

        if redact:
            self.city_combobox.setCurrentText(city)
            self.name_edit.setText(name)
            self.desc_edit.setPlainText(desc)
            self.image_edit.setText(image)

            self.lat_edit.setText("" if not lat else str(lat))
            self.lon_edit.setText("" if not lon else str(lon))

    def check(self):
        # получаем данные из полей
        city, name, *_ = self.get_data()

        # проверяем обязательные поля
        tx = []
        if not city:
            tx += ['Город']
        if not name.strip():
            tx += ['Название']
        if tx:
            if len(tx) == 1:
                s1 = 'Поле'
                s2 = 'обязательно'
            else:
                s1 = 'Поля'
                s2 = 'обязательны'
            s = s1 + ' "' + '", "'.join(tx) + '"'
            QMessageBox.warning(
                self, 'Ошибка',
                f'{s}'
                f' {s2} для заполнения!'
            )
            return

        if not self.par.valid_coord(self):
            return

        # закрываем окно с результатом ok
        self.accept()

    def get_data(self) -> tuple[str, str, str, str, float, float]:
        lat_text = self.lat_edit.text().strip()
        lon_text = self.lon_edit.text().strip()

        lat = float(lat_text) if lat_text else None
        lon = float(lon_text) if lon_text else None

        return (
            self.city_combobox.currentText(),
            self.name_edit.text(),
            self.desc_edit.toPlainText(),
            self.image_edit.text(),
            lat, lon
        )


class Project(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        # f = io.StringIO(template)
        # uic.loadUi(f, self)
        self.setupUi(self)
        self.db_name = 'data.db'
        self.map_name = '3840px-World_map_nations.png'
        self.get_path()
        self.protected_index = 1
        self.password = "1234"
        self.setWindowTitle('Интерактивная карта достопримечательностей')
        self.initUI()

    def initUI(self):
        # создаем горячую клавишу
        shortcut = QShortcut(QKeySequence("Shift+F"), self)
        shortcut.activated.connect(self.password_off)

        # подключаем класс-фильтр для запроса пароля
        self.filter = TabFilter(
            self, self.main_tabs, self.protected_index, self.password)
        self.main_tabs.tabBar().installEventFilter(self.filter)

        # устанавливаем вкладку по умолчанию
        self.main_tabs.setCurrentIndex(0)

        # устанавливаем выделение по строкам а не по ячейкам
        self.atr_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)

        # устанавливаем скрол нижнего ползунка по пикселям
        # а не по столбцам таблицы
        self.atr_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)

        # создаем карту
        lbl = self.map
        self.map = Map(lbl.parentWidget(), self.map_path)
        lbl.parentWidget().layout().replaceWidget(lbl, self.map)
        lbl.parentWidget().layout().setContentsMargins(0, 0, 0, 0)

        # панель поверх карты
        self.layers_panel = QWidget(self.map)
        self.layers_panel.setObjectName("layers_panel")

        # белый полупрозрачный фон, текст жирным
        self.layers_panel.setStyleSheet("""
            QWidget#layers_panel {
                background-color: rgba(255, 255, 255, 200);
            }
            QLabel {
                font-weight: bold
            }
        """)

        # Настраиваем внутренности панели
        panel_layout = QVBoxLayout(self.layers_panel)

        title = QLabel("Слои карты")
        panel_layout.addWidget(title)

        # Города
        self.cb_cities = QCheckBox("● Города")
        self.cb_cities.setChecked(True)

        # Красим только текст в синий, не трогая галочку
        pal_cities = self.cb_cities.palette()
        pal_cities.setColor(QPalette.ColorRole.WindowText, QColor("#0044CC"))
        self.cb_cities.setPalette(pal_cities)

        # Делаем шрифт жирным
        font_cities = self.cb_cities.font()
        font_cities.setBold(True)
        self.cb_cities.setFont(font_cities)

        self.cb_cities.stateChanged.connect(self.update_layers)
        panel_layout.addWidget(self.cb_cities)

        # Достопримечательности
        self.cb_atrs = QCheckBox("● Достопримечательности")
        self.cb_atrs.setChecked(True)

        # Красим только текст в красный
        pal_atrs = self.cb_atrs.palette()
        pal_atrs.setColor(QPalette.ColorRole.WindowText, QColor("#CC0000"))
        self.cb_atrs.setPalette(pal_atrs)

        # Делаем шрифт жирным
        font_atrs = self.cb_atrs.font()
        font_atrs.setBold(True)
        self.cb_atrs.setFont(font_atrs)

        self.cb_atrs.stateChanged.connect(self.update_layers)
        panel_layout.addWidget(self.cb_atrs)

        self.layers_panel.setFixedSize(220, 120)  # Фиксированный размер плашки

        # создаем меню сохранить и действия для нее
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu('Файл')
        redact_menu = menu_bar.addMenu('Справка')
        save_act = file_menu.addAction('Сохранить')
        new_city = file_menu.addAction('Добавить город')
        redact_city = file_menu.addAction('Изменить город')
        del_city = file_menu.addAction('Удалить город')
        about_act = redact_menu.addAction('О программе')
        how_to_use = redact_menu.addAction('Как пользоваться')

        # привязываем функции к событиям
        save_act.triggered.connect(self.save)
        new_city.triggered.connect(self.new_city)
        redact_city.triggered.connect(self.redact_city)
        del_city.triggered.connect(self.del_city)
        about_act.triggered.connect(self.about)
        how_to_use.triggered.connect(self.how_to_use)

        self.desc_atr_btn.clicked.connect(self.show_description)
        self.del_atr_btn.clicked.connect(self.del_row)
        self.change_atr_btn.clicked.connect(self.change_row)
        self.add_atr_btn.clicked.connect(self.new_row)

        self.upd_table()

    def upd_table(self, index=None):
        rows, headers = self.get_data()

        # очищаем таблицу
        self.atr_table.clear()

        # обновляем карту
        self.upd_map()

        if not rows or not headers:
            # чтоб не было пустых строк
            self.atr_table.setRowCount(0)
            return

        # задаем параметры для таблицы
        self.atr_table.setRowCount(len(rows))
        self.atr_table.setColumnCount(len(rows[0]))

        # устанавливаем заголовки
        self.atr_table.setHorizontalHeaderLabels(headers)

        # записываем значения в каждую ячейку
        for r, row in enumerate(rows):
            desc = str(row[3])
            for c, val in enumerate(row):
                display_val = "" if val is None else str(val)
                item = QTableWidgetItem(display_val)
                # ставим подсветку на строку при наведении
                # добавляем тег qt чтобы движок посчитал текст html строкой и
                # добавил переносы строк при подсветке. Иначе подсказка будет
                # в одну строку и займет всю ширину окна
                item.setToolTip(f'<qt>{desc}</qt>')
                self.atr_table.setItem(r, c, item)

        # скрываем колонку с id
        self.atr_table.setColumnHidden(0, True)

        h = self.atr_table.horizontalHeader()

        # настраиваем растягивание ячеек
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    @staticmethod
    def require_selection(func: Callable):
        '''Проверяет выделена ли строка в таблице'''
        # @wraps копирует имя и докстринг оригинальной функции,
        # чтобы при отладке выводилось правильное имя метода а не 'wrapper'
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # (если строка не выбрана вернет -1)
            r = self.atr_table.currentRow()
            if r == -1:
                QMessageBox.warning(
                    self, 'Предупреждение', 'Выберите строку таблицы')
                return
            return func(self, r)
        return wrapper

    @require_selection
    def show_description(self, r: int):
        # получаем описание из нажатой строки
        desc = self.atr_table.item(r, 3)
        QMessageBox.information(self, 'Полное описание', desc.text())

    @require_selection
    def del_row(self, r: int):
        ok = QMessageBox.question(
            self, 'Удаление', 'Вы уверены?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if ok == QMessageBox.StandardButton.Yes:
            id = int(self.atr_table.item(r, 0).text())
            self.execute('DELETE FROM attractions WHERE id = ?', (id,))
            self.upd_table()

    @require_selection
    def change_row(self, r: int):
        atr_id = int(self.atr_table.item(r, 0).text())
        city = self.atr_table.item(r, 1).text()
        name = self.atr_table.item(r, 2).text()
        desc = self.atr_table.item(r, 3).text()
        image = self.atr_table.item(r, 4).text()
        lat = self.atr_table.item(r, 5).text()
        lon = self.atr_table.item(r, 6).text()

        dialog = EditDialog(
            self, city, name, desc, image, lat, lon, redact=True)
        dialog.setWindowTitle('Изменение строки')

        if dialog.exec() == QDialog.DialogCode.Accepted:
            city, name, desc, image, lat, lon = dialog.get_data()

            self.execute(
                '''UPDATE attractions
                SET city_id = (SELECT id FROM cities WHERE name = ?),
                name = ?, description = ?, image_name = ?,
                lat = ?, lon = ?
                WHERE id = ?''',
                (city, name, desc, image, lat, lon, atr_id))
            self.upd_table()

            QMessageBox.information(self, 'Успех', 'Строка изменена')

    def new_row(self):
        dialog = EditDialog(self, redact=False)
        dialog.setWindowTitle('Создание новой строки')

        if dialog.exec() == QDialog.DialogCode.Accepted:
            city, name, desc, image, lat, lon = dialog.get_data()

            # COALESCE берет первое ненулевое значение
            self.execute('''
                    INSERT INTO attractions (
                        city_id, name, description, image_name, lat, lon
                    ) VALUES (
                        (SELECT id FROM cities WHERE name = ?), ?, ?, ?, ?, ?
                    )
                ''', (city, name, desc, image, lat, lon))
            self.upd_table()
            # заставляет пересчитать ширины столбцов
            self.atr_table.resizeColumnsToContents()

            last_row = self.atr_table.rowCount() - 1
            # установка новой строки
            self.atr_table.selectRow(last_row)
            self.atr_table.setCurrentCell(last_row, 1)
            # скролит вниз
            self.atr_table.scrollToBottom()

            QMessageBox.information(self, 'Успех', 'Строка добавлена')

    def execute(self, query: str, params: tuple = ()):
        # подключаем db
        with sl.connect(self.db_path) as con:
            cur = con.cursor()
            cur.execute(query, params)
            # сохраняем изменения в db и возвращаем id
            con.commit()

    def fetch(
            self, query: str, params: tuple = ()
    ) -> tuple[list[tuple[str | int, ...]], list[str]]:
        # подключаем db
        with sl.connect(self.db_path) as con:
            cur = con.cursor()
            cur.execute(query, params)
            # возвращаем результат
            # (после прошлого запроса
            # в курсоре хранятся данные о заголовках)
            headers = [d[0] for d in cur.description]
            rows = cur.fetchall()
            return rows, headers

    def get_data(self) -> tuple[list[tuple[str | int, ...]], list[str]]:
        return self.fetch('''
            SELECT atr.id, ct.name AS city_name,
            atr.name, atr.description, atr.image_name,
            atr.lat, atr.lon
            FROM cities AS ct
            JOIN attractions AS atr ON atr.city_id = ct.id
        ''')

    def get_path(self):
        # Если программа запущена как exe
        if getattr(sys, 'frozen', False):
            # для exe
            base_dir = os.path.dirname(sys.executable)
        else:
            # для py
            base_dir = os.path.dirname(os.path.abspath(__file__))

        self.db_path = os.path.join(base_dir, "data", self.db_name)
        self.map_path = os.path.join(base_dir, self.map_name)

    def save(self):
        fname = QFileDialog.getSaveFileName(
            self,
            'Сохранить файл', 'data',
            'EXCEL (*.xlsx);;CSV (*.csv);;Copy (*.db)'
        )[0]

        if not fname:
            return

        try:
            if fname.endswith('.db'):
                shutil.copy(self.db_path, fname)
                saved_info = fname
            elif fname.endswith('.csv'):
                res = self.export_to_csv(fname)
                saved_info = "\n".join(res)
            elif fname.endswith('.xlsx'):
                self.export_to_excel(fname)
                saved_info = fname
            else:
                QMessageBox.warning(self, 'Ошибка', 'Неизвестный формат файла')
                return

        except Exception as e:
            QMessageBox.critical(
                self, 'Ошибка', f'Не удалось сохранить файл:\n{e}')
        else:
            QMessageBox.information(
                self, 'Успех',
                f'Данные успешно сохранены в файл \n{saved_info}')

    def _get_export(self) -> dict[str, tuple[list[tuple], list[str]]]:
        atr_rows, atr_headers = self.get_data()
        city_rows, city_headers = self.fetch(
            'SELECT name, lat, lon FROM cities')
        return {
            'attractions': ([row[1:] for row in atr_rows], atr_headers[1:]),
            'cities': (city_rows, city_headers)
        }

    def export_to_csv(self, fname: str):
        base, _ = os.path.splitext(fname)
        created_files = []

        for table_name, (rows, headers) in self._get_export().items():
            new_fname = f"{base}_{table_name}.csv"
            with open(new_fname, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(headers)
                writer.writerows(rows)
            created_files.append(new_fname)

        return created_files

    def export_to_excel(self, fname: str):
        wb = op.Workbook()
        wb.remove(wb.active)

        sheet_names = {
            'attractions': 'Достопримечательности',
            'cities': 'Города'
        }

        for table_name, (rows, headers) in self._get_export().items():
            ws = wb.create_sheet(title=sheet_names[table_name])
            ws.append(headers)
            for row in rows:
                ws.append(row)

        wb.save(fname)

    def about(self):
        QMessageBox.information(
            self, 'О программе',
            "<h3>Интерактивная карта достопримечательностей</h3>"
            "<p><b>Версия:</b> 1.0</p>"
            "<p><b>Автор:</b> Белозёров Илья</p>"
            "<p><b>Описание:</b> Приложение для просмотра и управления "
            "базой данных городов и их достопримечательностей с "
            "интерактивной картой и возможностью экспорта отчетов.</p>"
            "<p><b>Используемые технологии:</b></p>"
            "<ul>"
            "<li>Python 3.11</li>"
            "<li>PyQt6 (графический интерфейс)</li>"
            "<li>QGraphicsView (интерактивная карта с зумом)</li>"
            "<li>SQLite3 (реляционная база данных)</li>"
            "<li>openpyxl и csv (экспорт данных)</li>"
            "</ul>"
            "<p><i>Курсовой проект, Яндекс Лицей, 2026 г.</i></p>"
        )

    def how_to_use(self):
        QMessageBox.information(
            self, 'Как пользоваться',
            "<h3>Интерактивная карта достопримечательностей</h3>"
            "<p><b>Вкладка «Карта»:</b></p>"
            "<ul>"
            "<li><b>Перетаскивание:</b> зажмите левую кнопку мыши и "
            "двигайте карту.</li>"
            "<li><b>Масштабирование:</b> используйте колесико мыши, чтобы "
            "приблизить или отдалить карту.</li>"
            "<li><b>Слои:</b> используйте галочки в левом верхнем углу, "
            "чтобы скрыть или показать города и достопримечательности.</li>"
            "<li><b>Информация:</b> кликните по синему или красному маркеру, "
            "чтобы увидеть подробности.</li>"
            "</ul>"
            "<p><b>Вкладка «Таблица»:</b></p>"
            "<ul>"
            "<li>Отображает все достопримечательности с указанием города.</li>"
            "<li>Наведите курсор на строку — появится всплывающая подсказка "
            "с полным описанием.</li>"
            "<li>Выделите строку и нажмите <b>«Подробнее»</b>, чтобы "
            "прочитать полный текст.</li>"
            "</ul>"
            "<p><b>Управление данными:</b></p>"
            "<ul>"
            "<li><b>«Добавить» / «Изменить» / «Удалить»</b> — работа с "
            "достопримечательностями.</li>"
            "<li><b>Меню «Файл»</b> — добавление, изменение и удаление "
            "городов (при изменении города можно задать его координаты "
            "для отображения на карте).</li>"
            "<li><b>«Сохранить»</b> — экспорт данных в форматы .db, .csv "
            "или .xlsx.</li>"
            "</ul>"
            "<p><b>Безопасность:</b></p>"
            "<p>Переход на вкладку «Админка» защищён паролем "
            f"(по умолчанию: <code>{self.password}</code>).</p>"
        )

    def new_city(self):
        dialog = CityDialog(self, mode='add')
        dialog.setWindowTitle('Добавление города')

        if dialog.exec() == QDialog.DialogCode.Accepted:
            res = dialog.get_data()
            if not res:
                return
            name, lat, lon = res

            if not name:
                QMessageBox.warning(self, 'Ошибка', 'Введите название!')
                return

            if self.fetch('SELECT id FROM cities WHERE name = ?', (name,))[0]:
                QMessageBox.warning(self, 'Ошибка', 'Такой город уже есть!')
                return

            self.execute(
                'INSERT INTO cities (name, lat, lon) VALUES (?, ?, ?)',
                (name, lat, lon)
            )

            self.upd_table()
            QMessageBox.information(self, 'Успех!', f'Город {name} добавлен')

    def redact_city(self):
        if not self.fetch('SELECT name FROM cities')[0]:
            QMessageBox.warning(self, 'Ошибка', 'В базе нет городов')
            return

        dialog = CityDialog(self, mode='edit')
        dialog.setWindowTitle('Изменение города')

        if dialog.exec() == QDialog.DialogCode.Accepted:
            res = dialog.get_data()
            if not res:
                return
            name, lat, lon = res

            self.execute(
                'UPDATE cities SET lat = ?, lon = ? WHERE name = ?',
                (lat, lon, name)
            )
            self.upd_table()
            QMessageBox.information(self, 'Успех', f'Город {name} обновлен')

    def del_city(self):
        rows = self.fetch(
            'SELECT name FROM cities'
        )[0]

        if not rows:
            QMessageBox.warning(
                self, 'Ошибка', 'В базе нет городов')
            return

        city_names = [row[0] for row in rows]
        city_name, ok = QInputDialog.getItem(
            self, 'Удаление города', 'Выберите город для удаления:',
            [''] + city_names, 0, False
        )

        if not ok:
            return

        if not city_name:
            QMessageBox.warning(
                self, 'Предупреждение', 'Выберите город')
            return

        ok = QMessageBox.question(
            self, 'Подтверждение',
            f'Вы уверены, что хотите удалить город "{city_name}"?\n'
            f'ВСЕ его достопримечательности будут также удалены!',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if ok == QMessageBox.StandardButton.Yes:
            id = self.fetch(
                'SELECT id FROM cities WHERE name = ?',
                (city_name,)
            )[0][0][0]

            self.execute(
                'DELETE FROM cities WHERE id = ?', (id,)
            )

            self.upd_table()

            QMessageBox.information(
                self, 'Успех',
                f'Город "{city_name}" и все его достопримечательности удалены!'
            )

    def password_off(self):
        self.filter.enabled = not self.filter.enabled
        state = "выключен" if not self.filter.enabled else "включён"
        self.statusBar().showMessage(f'Пароль {state}', 3000)

    def upd_map(self):
        cities = self.fetch('SELECT name, lat, lon FROM cities')[0]
        attractions = self.fetch('SELECT name, lat, lon FROM attractions')[0]
        self.map.set_ct_and_atr(cities, attractions)

    def update_layers(self):
        self.map.set_layers(
            self.cb_cities.isChecked(),
            self.cb_atrs.isChecked()
        )

    def valid_coord(self, ss: CityDialog | EditDialog) -> bool:
        # проверка на ошибки
        lat_text = ss.lat_edit.text().strip()
        lon_text = ss.lon_edit.text().strip()

        if not lat_text and not lon_text:
            return True

        if not lat_text or not lon_text:
            QMessageBox.critical(
                self, 'Ошибка',
                'Заполните обе координаты или оставьте оба поля пустыми')
            return False

        try:
            lat = float(lat_text)
            lon = float(lon_text)
        except ValueError:
            QMessageBox.critical(
                self, 'Ошибка', 'Широта и долгота должны быть числами')
            return False

        # проверка на возможность
        coord_name = []
        if lat < -90 or lat > 90:
            coord_name.append('широты')
        if lon < -180 or lon > 180:
            coord_name.append('долготы')
        if coord_name:
            QMessageBox.critical(
                self, 'Ошибка',
                f"Несуществующее значение {', '.join(coord_name)}")
            return False

        # проверка на границы карты
        coord_name = []
        if lat > Map.LAT_TOP or lat < Map.LAT_BOTTOM:
            coord_name.append('широты')
        if lon < Map.LON_LEFT or lon > Map.LON_RIGHT:
            coord_name.append('долготы')
        if coord_name:
            ok = QMessageBox.question(
                self, 'Предупреждение',
                f'Значение {coord_name} выходит за пределы этой карты, '
                'поэтому точка на ней не появится\nВы уверены?',
                QMessageBox.StandardButton.Ok |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            if ok != QMessageBox.StandardButton.Ok:
                return False

        return True


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = Project()
    ex.show()
    app.exec()
