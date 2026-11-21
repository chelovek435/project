import sys
import os
import shutil
import csv
import openpyxl as op
# import io
# from PyQt6 import uic
import sqlite3 as sl
from PyQt6.QtWidgets import (QApplication, QMainWindow,
                             QMessageBox, QTableWidgetItem, QHeaderView,
                             QAbstractItemView, QDialog, QFileDialog, QLabel,
                             QWidget, QVBoxLayout, QCheckBox, QToolTip,
                             QGraphicsView, QGraphicsScene,
                             QGraphicsPixmapItem, QGraphicsEllipseItem,
                             QGraphicsSimpleTextItem, QGraphicsItem)
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import (QPixmap, QPainter, QPen, QBrush,
                         QColor, QFont, QPalette)
from PyQt6.QtWidgets import QFrame

from UI.u import Ui_MainWindow
from UI.u2 import Ui_Dialog as Ui_AtrDialog
from UI.u3 import Ui_Dialog as Ui_CityDialog
from UI.u4 import Ui_Dialog as Ui_InfoDialog

template = """"""


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

        # отключаем ползунки и их угловые элементы
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # устанавливаем цвет фона окна
        self.setBackgroundBrush(QBrush(QColor("#cceeff")))
        # задаем сцене границы
        self.scene.setSceneRect(0, 0, self.pix.width(), self.pix.height())

        # сглаживание линий и легкое размытие чтоб хуже было видно пиксели
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # возможность перетаскивать карту
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        # приближение камеры в место где находится мышка
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # сохранение текущего положения камеры при изменении размеров окна
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        self.cities = []
        self.attractions = []
        self.show_cities = True
        self.show_atrs = True
        self.marker_items = []
        self._user_zoomed = False
        self.highlighted_name = None
        self.current_tooltip_name = None

        # подключаем отслеживание мышки
        self.setMouseTracking(True)

        # Создаем виджет для масштаба
        self.scale_label = QLabel("Масштаб", self)
        # выравнивание по центру
        self.scale_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # черная полоска чтоб было понятно масштаб чего написан
        self.scale_line = QWidget(self)
        # цвет, размер
        self.scale_line.setStyleSheet("background-color: black;")
        self.scale_line.setFixedHeight(3)
        self.scale_line.setFixedWidth(100)

        # обновление размеров полоски и значения
        # относительно текущего размера экрана
        self.update_scale()

    def _get_min_scale(self) -> float:
        # вычисляем минимальный коэфф масштабирования
        # (параметры окошка / параметры сцены)
        return max(
            self.viewport().width() / self.scene.sceneRect().width(),
            self.viewport().height() / self.scene.sceneRect().height()
        )

    def _fit_map(self):
        # вписываем сцену в видимое окошко полностью
        self.fitInView(
            self.scene.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )

    def update_scale(self):
        # получаем коэффициент зума(во сколько раз увеличены пиксели)
        current_scale = self.transform().m11()

        # 40075 км - длина экватора
        # сколько километров в одном пикселе на текущем зуме
        km_per_pixel = (40075 / self.pix.width()) / current_scale

        # пусть полоска занимает 1/5 текущей ширины окна
        target_pixels = int(self.width() / 5)

        target_km = target_pixels * km_per_pixel

        # форматируем отображение
        if target_km >= 1000:
            text = f"{target_km/1000:.1f} тыс. км"
        elif target_km >= 1:
            text = f"{target_km:.1f} км"
        else:
            text = f"{target_km*1000:.1f} м"

        self.scale_label.setText(text)

        self.scale_line.setFixedWidth(target_pixels)

        center_x = self.width() // 2
        # пусть будет отступ 15 пикселей снизу
        line_y = self.height() - 15

        # центрируем полоску
        line_x = center_x - (target_pixels // 2)
        self.scale_line.move(line_x, line_y)

        # центрируем лейбл
        label_x = center_x - (self.scale_label.width() // 2)
        # отступ 2 пикселя между лейблом и полоской
        label_y = line_y - self.scale_label.height() - 2
        self.scale_label.move(label_x, label_y)

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
            return

        # находим отношение длин в координатах и переводим в пиксели
        x = (lon - self.LON_LEFT) / (
            self.LON_RIGHT - self.LON_LEFT) * self.pix.width()
        # тут подвох:
        # в компьютерной графике ось Y наоборот поэтому вычитаем наоборот,
        # чтобы карта не перевернулась и не было отрицательных пикселей
        y = (self.LAT_TOP - lat) / (
            self.LAT_TOP - self.LAT_BOTTOM) * self.pix.height()
        return QPointF(x, y)

    def _create_marker(
        self, name: str, pos: QPointF, marker_type: str,
        radius: int, fill_color, border_color, border_width: int, z_value: int
    ) -> QGraphicsEllipseItem:
        # ставим такие размеры, чтобы центр был в 0, 0
        circle = QGraphicsEllipseItem(-radius, -radius, radius * 2, radius * 2)
        # флаг не дает маркерам растягиваться
        # во время приближения, чтобы
        # каждую метку было отчетливо видно и они не слипались
        circle.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        circle.setBrush(QBrush(fill_color))
        circle.setPen(QPen(border_color, border_width))
        # устанавливаем слой
        circle.setZValue(z_value)
        circle.setPos(pos)
        # сохраняем информацию,
        # чтобы позже при клике можно было получить ее
        circle.setData(0, marker_type)
        circle.setData(1, name)

        self.scene.addItem(circle)
        self.marker_items.append(circle)
        return circle

    def redraw_markers(self):
        # удаляем маркеры и очищаем список
        for item in self.marker_items:
            self.scene.removeItem(item)
        self.marker_items.clear()

        if self.show_cities:
            font = QFont("Arial", 11)
            font.setBold(True)

            for name, lat, lon in self.cities:
                pos = self._latlon_to_scene(lat, lon)
                if pos:
                    circle = self._create_marker(
                        name, pos, "city", radius=12,
                        fill_color=Qt.GlobalColor.blue,
                        border_color=Qt.GlobalColor.darkBlue,
                        border_width=2, z_value=10
                    )
                    text = QGraphicsSimpleTextItem(name)
                    text.setParentItem(circle)
                    text.setFont(font)
                    text.setPos(16, -12)

        if self.show_atrs:
            for name, lat, lon in self.attractions:
                pos = self._latlon_to_scene(lat, lon)
                if pos:
                    if name.strip() == self.highlighted_name:
                        self._create_marker(
                            name, pos, "attraction", radius=14,
                            fill_color=Qt.GlobalColor.green,
                            border_color=Qt.GlobalColor.darkGreen,
                            border_width=3, z_value=20
                        )
                    else:
                        self._create_marker(
                            name, pos, "attraction", radius=9,
                            fill_color=Qt.GlobalColor.red,
                            border_color=Qt.GlobalColor.darkRed,
                            border_width=2, z_value=5
                        )

    def wheelEvent(self, event):
        # если картинки нет
        if self.pix.isNull():
            return

        # коэффициенты увеличения и уменьшения
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor

        # значение прокручивания колесика:
        # если вверх - приближаем, вниз - отдаляем
        if event.angleDelta().y() > 0:
            zoom_factor = zoom_in_factor
        else:
            zoom_factor = zoom_out_factor

        # вычисляем масштаб, который получится после прокрутки
        new_scale = self.transform().m11() * zoom_factor

        # считаем минимально возможный масштаб для текущего размера окна
        # (параметры видимого окна / параметры всей сцены)
        min_scale = self._get_min_scale()

        # ограничиваем максимальное приближение
        max_scale = 4000.0
        if zoom_factor > 1 and new_scale >= max_scale:
            return

        # Если мы отдаляем карту и достигли предела
        if zoom_factor < 1 and new_scale <= min_scale:
            # Сбрасываем флаг, чтобы карта снова стала недвижимой,
            # как при старте
            self._user_zoomed = False
            # вписывает всю сцену в окно, увеличивая картинку до того размера,
            # чтобы не было видно краев сцены
            self._fit_map()
            self.update_scale()
            return

        # Если все ок - применяем зум
        self._user_zoomed = True
        self.scale(zoom_factor, zoom_factor)

        self.update_scale()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pix.isNull():
            return

        if (
            not self._user_zoomed
            or self.transform().m11() < self._get_min_scale()
        ):
            self._fit_map()

        self.update_scale()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Получаем элемент под курсором
            item = self.itemAt(event.position().toPoint())

            # Если это маркер города или достопримечательности
            if item and item.data(0) in ["city", "attraction"]:
                item_type = item.data(0)
                name = item.data(1)

                # Если кликнули по подсвеченной зелёной точке -
                # снимаем выделение
                if name.strip() == self.highlighted_name:
                    self.highlighted_name = None
                    self.redraw_markers()

                # Просим главное окно показать инфу
                self.window().show_marker_info(name, item_type)
                return  # Выходим, чтобы карта не начала перетаскиваться

        super().mousePressEvent(event)

    def center_on(self, lat: float, lon: float, name=None):
        pos = self._latlon_to_scene(lat, lon)
        if pos:
            # Очищаем от пробелов на всякий случай
            self.highlighted_name = name.strip() if name else None
            # сбрасываем зум и приближаем
            self.resetTransform()
            self.scale(1000.0, 1000.0)
            self.centerOn(pos)  # центрируем
            self._user_zoomed = True
            self.redraw_markers()
            self.update_scale()

    def mouseMoveEvent(self, event):
        '''встроенный .setToolTip() показывает подсказки только через время,
        а этот моментально'''
        super().mouseMoveEvent(event)

        item = self.itemAt(event.position().toPoint())

        # Если курсор над маркером
        if item and item.data(0) == "attraction":
            name = item.data(1)

            # Показываем подсказку только если она изменилась
            if name != self.current_tooltip_name:
                QToolTip.showText(event.globalPosition().toPoint(), name, self)
                self.current_tooltip_name = name
        else:
            # Прячем подсказку только если она была открыта
            if self.current_tooltip_name is not None:
                QToolTip.hideText()
                self.current_tooltip_name = None


class InfoDialog(QDialog, Ui_InfoDialog):
    def __init__(self, parent: "Project", title, description, image_names):
        super().__init__(parent)
        self.par = parent
        self.title = title
        self.ind = 0
        self.is_hide = False
        self.setupUi(self)
        self.setWindowTitle('Достопримечательность')
        self.title_lbl.setText(title)
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # фиксированный размер чтобы не скакал интерфейс
        self.image_lbl.setFixedSize(450, 250)

        # если у нас город
        if image_names is None:
            self.image_lbl.hide()
            self.desc_browser.setHtml(description)
        else:
            self.desc_browser.setPlainText(
                description if description else "Описание отсутствует"
            )

        # кликабельные ссылки
        self.desc_browser.setOpenLinks(False)
        self.desc_browser.anchorClicked.connect(self._on_link_click)

        self.left_btn.clicked.connect(self.change_image)
        self.right_btn.clicked.connect(self.change_image)

        if image_names:
            self.images = [
                img.strip() for img in str(image_names).split(',')
                if img.strip()
            ]
        else:
            self.images = []

        self.ln = len(self.images)

        if self.ln <= 1:
            self.is_hide = True
            self.left_btn.hide()
            self.right_btn.hide()

        self.close_btn.clicked.connect(self.accept)

        self.change_image()

    def change_image(self):
        if not self.images:
            self.image_lbl.clear()
            self.image_lbl.setText('Фото отсутствует')
            return

        snd = self.sender()
        if snd:
            # зацикливаем список
            if snd == self.left_btn:
                self.ind = (self.ind - 1) % self.ln
            elif snd == self.right_btn:
                self.ind = (self.ind + 1) % self.ln

        image_name = self.images[self.ind]

        if not image_name:
            self.image_lbl.clear()
            self.image_lbl.setText('Фото отсутствует')
            return

        if not self.is_hide:
            self.title_lbl.setText(self.title + f' ({self.ind + 1}/{self.ln})')

        # Ищем картинку рядом с базой данных
        cd = os.path.dirname(self.par.db_path)
        img_path = os.path.join(cd, "photos", image_name)

        if os.path.exists(img_path):
            pixmap = QPixmap(img_path)
            # Масштабируем картинку, чтобы она влезла в окно
            self.image_lbl.setPixmap(pixmap.scaled(
                450, 250,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        else:
            self.image_lbl.clear()
            self.image_lbl.setText('Фото отсутствует')

    def _on_link_click(self, url):
        self.par.show_marker_info(url.toString(), "attraction")


class CityDialog(QDialog, Ui_CityDialog):
    def __init__(self, parent: "Project", name='', lat='', lon='',
                 redact=False):
        super().__init__(parent)
        self.par = parent
        self.setWindowTitle(
            'Редактирование города' if redact else 'Добавление города')
        self.setupUi(self)

        self.city_edit.show()
        self.label_3.setText('Название города:')

        self.ok_btn.clicked.connect(self.check)
        self.cancel_btn.clicked.connect(self.reject)

        if redact:
            self.city_edit.setText(name)
            self.lat_edit.setText("" if not lat else str(lat))
            self.lon_edit.setText("" if not lon else str(lon))

    def check(self):
        if not self.city_edit.text().strip():
            QMessageBox.warning(self, 'Ошибка', 'Введите название города')
            return
        if not self.par.valid_coord(self):
            return
        self.accept()

    def get_data(self) -> tuple[str, float | None, float | None]:
        lat_text = self.lat_edit.text().strip()
        lon_text = self.lon_edit.text().strip()
        return (
            self.city_edit.text().strip(),
            float(lat_text) if lat_text else None,
            float(lon_text) if lon_text else None
        )


class AtrDialog(QDialog, Ui_AtrDialog):
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
        self.init_db()
        self.setWindowTitle('Интерактивная карта достопримечательностей')
        self.initUI()

    def initUI(self):
        # Подключаем двойной клик по строке таблицы
        self.atr_table.cellDoubleClicked.connect(self.zoom_to_marker)
        self.ct_table.cellDoubleClicked.connect(self.zoom_to_marker)

        # устанавливаем вкладку по умолчанию
        self.main_tabs.setCurrentIndex(0)

        # устанавливаем выделение по строкам а не по ячейкам
        self.atr_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.ct_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)

        # устанавливаем скрол нижнего ползунка по пикселям
        # а не по столбцам таблицы
        self.atr_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.ct_table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)

        # отключаем редактирование при двойном клике
        self.atr_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ct_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)

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
        save_act = file_menu.addAction('Экспорт')
        import_menu = file_menu.addMenu('Импорт')
        import_append_act = import_menu.addAction('Дополнить и обновить')
        import_replace_act = import_menu.addAction('Заменить текущую базу')
        about_act = redact_menu.addAction('О программе')
        how_to_use = redact_menu.addAction('Как пользоваться')

        # привязываем функции к событиям
        save_act.triggered.connect(self.save)
        import_append_act.triggered.connect(
            lambda: self.import_data(replace=False))
        import_replace_act.triggered.connect(
            lambda: self.import_data(replace=True))
        about_act.triggered.connect(self.about)
        how_to_use.triggered.connect(self.how_to_use)

        self.desc_atr_btn.clicked.connect(self.show_description)
        self.del_atr_btn.clicked.connect(self.del_row)
        self.change_atr_btn.clicked.connect(self.change_row)
        self.add_atr_btn.clicked.connect(self.new_row)

        self.add_ct_btn.clicked.connect(self.new_city)
        self.change_ct_btn.clicked.connect(self.redact_city)
        self.del_ct_btn.clicked.connect(self.del_city)

        self.upd_table()

    def upd_table(self):
        self.upd_atr_table()
        self.upd_ct_table()
        self.upd_map()

    def _fill_table(
        self, table, rows: list, headers: list, tooltip_col: int | None = None
    ):
        table.clear()
        if not rows or not headers:
            # чтоб не было пустых строк
            table.setRowCount(0)
            return

        table.setRowCount(len(rows))
        table.setColumnCount(len(rows[0]))
        table.setHorizontalHeaderLabels(headers)

        for r, row in enumerate(rows):
            # добавляем тег qt чтобы движок посчитал текст html
            # строкой и добавил переносы строк. Иначе подсказка будет
            # в одну строку и займет всю ширину окна
            tip = f'<qt>{row[tooltip_col]}</qt>' if (
                tooltip_col is not None) else None
            for c, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else str(val))
                if tip:
                    # ставим подсветку на строку при наведении
                    item.setToolTip(tip)
                table.setItem(r, c, item)

        table.setColumnHidden(0, True)

    def upd_atr_table(self, index=None):
        rows, headers = self.get_data()
        self._fill_table(self.atr_table, rows, headers, tooltip_col=3)

        h = self.atr_table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def upd_ct_table(self):
        rows, headers = self.fetch('SELECT id, name, lat, lon FROM cities')
        self._fill_table(self.ct_table, rows, headers)

        h = self.ct_table.horizontalHeader()
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

    def init_db(self):
        # Создаём папку data, если её случайно удалили
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with sl.connect(self.db_path) as con:
            cur = con.cursor()
            # Включаем поддержку внешних ключей (для каскадного удаления)
            cur.execute('PRAGMA foreign_keys = ON')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS cities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    lat REAL,
                    lon REAL
                )
            ''')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS attractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    image_name TEXT,
                    lat REAL,
                    lon REAL,
                    FOREIGN KEY (city_id) REFERENCES cities(id)
                    ON DELETE CASCADE
                )
            ''')
            con.commit()

    def get_selected_row(self, table) -> int | None:
        r = table.currentRow()
        if r == -1:
            QMessageBox.warning(
                self, 'Предупреждение', 'Выберите строку таблицы')
            return None
        return r

    def show_description(self):
        r = self.get_selected_row(self.atr_table)
        if r is None:
            return
        # получаем описание из нажатой строки
        desc = self.atr_table.item(r, 3)
        QMessageBox.information(self, 'Полное описание', desc.text())

    def del_row(self):
        r = self.get_selected_row(self.atr_table)
        if r is None:
            return
        ok = QMessageBox.question(
            self, 'Удаление', 'Вы уверены?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if ok == QMessageBox.StandardButton.Yes:
            id = int(self.atr_table.item(r, 0).text())
            self.execute('DELETE FROM attractions WHERE id = ?', (id,))
            self.upd_table()

    def change_row(self):
        r = self.get_selected_row(self.atr_table)
        if r is None:
            return
        atr_id = int(self.atr_table.item(r, 0).text())
        city = self.atr_table.item(r, 1).text()
        name = self.atr_table.item(r, 2).text()
        desc = self.atr_table.item(r, 3).text()
        image = self.atr_table.item(r, 4).text()
        lat = self.atr_table.item(r, 5).text()
        lon = self.atr_table.item(r, 6).text()

        dialog = AtrDialog(
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
        dialog = AtrDialog(self, redact=False)
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
            # для каскадного удаления
            cur.execute('PRAGMA foreign_keys = ON')
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
        self.map_path = os.path.join(base_dir, "data", self.map_name)

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
            "интерактивной картой, галереей фотографий и поддержкой "
            "экспорта и импорта отчётов.</p>"
            "<p><b>Используемые технологии:</b></p>"
            "<ul>"
            "<li>Python 3.11</li>"
            "<li>PyQt6 (графический интерфейс)</li>"
            "<li>QGraphicsView (интерактивная карта с масштабированием)</li>"
            "<li>SQLite3 (реляционная база данных с каскадным удалением)</li>"
            "<li>openpyxl и csv (экспорт и импорт таблиц)</li>"
            "</ul>"
            "<p><i>Курсовой проект, Яндекс Лицей, 2026 г.</i></p>"
        )

    def how_to_use(self):
        QMessageBox.information(
            self, 'Как пользоваться',
            "<h3>Интерактивная карта достопримечательностей</h3>"
            "<p><b>Вкладка «Карта»:</b></p>"
            "<ul>"
            "<li><b>Навигация:</b> зажмите левую кнопку мыши для "
            "перетаскивания карты и крутите колёсико для изменения масштаба."
            "</li><li><b>Слои:</b> используйте панель в левом верхнем углу, "
            "чтобы скрывать или показывать города и достопримечательности.</li"
            "><li><b>Карточки объектов:</b> кликните по синему маркеру города,"
            " чтобы увидеть его координаты и кликабельный список "
            "достопримечательностей, или по красному маркеру — для просмотра "
            "описания и галереи фотографий.</li>"
            "</ul>"
            "<p><b>Вкладка «Таблицы»:</b></p>"
            "<ul>"
            "<li>Разделена на две вкладки: <b>«Достопримечательности»</b> и "
            "<b>«Города»</b>.</li>"
            "<li><b>Быстрый переход:</b> двойной клик по любой строке "
            "переместит карту прямо к выбранному объекту.</li>"
            "<li><b>Управление записями:</b> используйте кнопки под таблицами "
            "для добавления, изменения и удаления данных (при добавлении "
            "нескольких фото указывайте имена файлов через запятую).</li>"
            "</ul>"
            "<p><b>Меню «Файл»:</b></p>"
            "<ul>"
            "<li><b>Экспорт:</b> сохранение всей базы данных в форматы "
            "<code>.xlsx</code>, <code>.csv</code> или <code>.db</code>.</li>"
            "<li><b>Импорт:</b> загрузка данных из файлов с выбором режима — "
            "<i>дополнить и обновить</i> текущую базу или <i>полностью "
            "заменить</i> её.</li>"
            "</ul>"
        )

    def new_city(self):
        dialog = CityDialog(self, redact=False)
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
        r = self.get_selected_row(self.ct_table)
        if r is None:
            return
        city_id = int(self.ct_table.item(r, 0).text())
        old_name = self.ct_table.item(r, 1).text()
        lat = self.ct_table.item(r, 2).text()
        lon = self.ct_table.item(r, 3).text()

        dialog = CityDialog(self, old_name, lat, lon, redact=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, lat, lon = dialog.get_data()
            if name != old_name and self.fetch(
                'SELECT id FROM cities WHERE name = ?', (name,)
            )[0]:
                QMessageBox.warning(
                    self, 'Ошибка', 'Город с таким названием уже существует!')
                return

            self.execute(
                'UPDATE cities SET name = ?, lat = ?, lon = ? WHERE id = ?',
                (name, lat, lon, city_id)
            )
            self.upd_table()
            QMessageBox.information(self, 'Успех', f'Город {name} обновлён')

    def del_city(self):
        r = self.get_selected_row(self.ct_table)
        if r is None:
            return
        city_id = int(self.ct_table.item(r, 0).text())
        city_name = self.ct_table.item(r, 1).text()

        ok = QMessageBox.question(
            self, 'Подтверждение',
            f'Вы уверены, что хотите удалить город "{city_name}"?\n'
            f'ВСЕ его достопримечательности будут также удалены!',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if ok == QMessageBox.StandardButton.Yes:
            self.execute('DELETE FROM cities WHERE id = ?', (city_id,))
            self.upd_table()

    def upd_map(self):
        cities = self.fetch('SELECT name, lat, lon FROM cities')[0]
        attractions = self.fetch('SELECT name, lat, lon FROM attractions')[0]
        self.map.set_ct_and_atr(cities, attractions)

    def update_layers(self):
        self.map.set_layers(
            self.cb_cities.isChecked(),
            self.cb_atrs.isChecked()
        )

    def valid_coord(self, ss: CityDialog | AtrDialog) -> bool:
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

    def clear_db(self):
        with sl.connect(self.db_path) as con:
            cur = con.cursor()
            cur.execute('DELETE FROM attractions')
            cur.execute('DELETE FROM cities')
            cur.execute(
                "DELETE FROM sqlite_sequence "
                "WHERE name IN ('cities', 'attractions')"
            )
            con.commit()

    def import_data(self, replace: bool = False):
        if replace:
            ok = QMessageBox.question(
                self, 'Подтверждение',
                'Текущая база данных будет полностью очищена и заменена '
                'данными из файла.\nПродолжить?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if ok != QMessageBox.StandardButton.Yes:
                return

        fname = QFileDialog.getOpenFileName(
            self, 'Импорт данных', '',
            'Все поддерживаемые файлы (*.xlsx *.csv *.db);;'
            'Excel (*.xlsx);;CSV (*.csv);;База данных (*.db)'
        )[0]
        if not fname:
            return

        try:
            if fname.endswith('.db'):
                if replace:
                    self._load_db_file(fname)
                    self.init_db()
                else:
                    QMessageBox.warning(
                        self, 'Ошибка',
                        'Файл .db можно импортировать только в режиме замены'
                    )
                    return
            elif fname.endswith('.xlsx'):
                if replace:
                    self.clear_db()
                self._parse_excel(fname)
            elif fname.endswith('.csv'):
                if replace:
                    self.clear_db()
                self._parse_csv(fname)
            else:
                QMessageBox.warning(self, 'Ошибка', 'Неизвестный формат файла')
                return

            self.upd_table()
            QMessageBox.information(
                self, 'Успех', 'Данные успешно импортированы!')

        except Exception as e:
            QMessageBox.critical(
                self, 'Ошибка', f'Не удалось выполнить операцию:\n{e}')

    def _load_db_file(self, fname):
        shutil.copy(fname, self.db_path)

    def _parse_excel(self, fname):
        wb = op.load_workbook(fname, read_only=True, data_only=True)
        with sl.connect(self.db_path) as con:
            cur = con.cursor()

            if 'Города' in wb.sheetnames:
                rows = wb['Города'].iter_rows(min_row=2, values_only=True)
                self._process_rows(cur, rows, is_city=True)

            if 'Достопримечательности' in wb.sheetnames:
                rows = wb['Достопримечательности'].iter_rows(
                    min_row=2, values_only=True)
                self._process_rows(cur, rows, is_city=False)

            con.commit()
        wb.close()

    def _parse_csv(self, fname):
        base_dir = os.path.dirname(fname)
        base_name = os.path.basename(fname)

        cities_file = None
        atrs_file = None

        if base_name.endswith('_cities.csv'):
            # Если выбрали файл городов, ищем достопримечательности рядом
            second_name = base_name.replace('cities', 'attractions')
            cities_file = fname
            atrs_file = os.path.join(base_dir, second_name)
        elif base_name.endswith('_attractions.csv'):
            # Если выбрали файл достопримечательностей, ищем города рядом
            second_name = base_name.replace('attractions', 'cities')
            cities_file = os.path.join(base_dir, second_name)
            atrs_file = fname
        else:
            # Если имя непонятное, заглядываем внутрь файла и считаем колонки
            with open(fname, encoding='utf-8') as f:
                reader = csv.reader(f, delimiter=';')
                try:
                    header = next(reader)  # Читаем первую строку (заголовки)
                except StopIteration:
                    return  # Файл пустой

                if len(header) == 3:
                    # Если 3 колонки, значит это города
                    cities_file = fname
                elif len(header) == 6:
                    # Если 6, значит это достопримечательности
                    atrs_file = fname
                else:
                    QMessageBox.critical(
                        self, "Ошибка",
                        "Файл не похож ни на список городов, ни на список "
                        "достопримечательностей. "
                        "Проверьте количество столбцов."
                    )
                    return

        with sl.connect(self.db_path) as con:
            cur = con.cursor()

            # Читаем города (если они есть)
            if cities_file and os.path.exists(cities_file):
                with open(cities_file, encoding='utf-8') as f:
                    reader = csv.reader(f, delimiter=';')
                    next(reader, None)  # Пропускаем заголовки
                    self._process_rows(cur, reader, is_city=True)

            # Читаем достопримечательности (если они есть)
            if atrs_file and os.path.exists(atrs_file):
                with open(atrs_file, encoding='utf-8') as f:
                    reader = csv.reader(f, delimiter=';')
                    next(reader, None)  # Пропускаем заголовки
                    self._process_rows(cur, reader, is_city=False)

            con.commit()

    def _clean_values(self, row, n):
        res = []
        # если данных не хватает они станут None
        for val in (list(row) + [None] * n)[:n]:
            if val is None:
                res.append(None)
                continue
            val = str(val).strip()
            res.append(val if val != "" else None)
        return res

    def _save_city(self, cur: sl.Cursor, row: list):
        if not row:
            return
        name, lat, lon = self._clean_values(row, 3)
        name = name if name else ''
        if not name:
            return

        lat = self._safe_float(lat)
        lon = self._safe_float(lon)

        # если такой город есть он обновит координаты
        cur.execute('''
            INSERT INTO cities (name, lat, lon) VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET lat=excluded.lat, lon=excluded.lon
        ''', (name, lat, lon))

    def _save_attraction(self, cur: sl.Cursor, row: list):
        city_name, name, desc, image, lat, lon = self._clean_values(row, 6)

        if not city_name or not name:
            return

        lat = self._safe_float(lat)
        lon = self._safe_float(lon)

        desc = str(desc) if desc is not None else ''
        image = str(image) if image is not None else ''

        cur.execute('INSERT OR IGNORE INTO cities (name) VALUES (?)',
                    (city_name,))

        city_id = cur.execute(
            'SELECT id FROM cities WHERE name = ?', (city_name,)
        ).fetchone()[0]

        existing = cur.execute(
            'SELECT id FROM attractions WHERE city_id = ? AND name = ?',
            (city_id, name)
        ).fetchone()

        if existing:
            cur.execute('''
                UPDATE attractions
                SET description = ?, image_name = ?, lat = ?, lon = ?
                WHERE id = ?
            ''', (desc, image, lat, lon, existing[0]))
        else:
            cur.execute('''
                INSERT INTO attractions
                (city_id, name, description, image_name, lat, lon)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (city_id, name, desc, image, lat, lon))

    def _process_rows(self, cur, rows, is_city):
        for row in rows:
            if is_city:
                self._save_city(cur, row)
            else:
                self._save_attraction(cur, row)

    def _safe_float(self, val):
        if val is None:
            return None
        try:
            return float(val)
        except ValueError:
            return None

    def show_marker_info(self, name, marker_type):
        if marker_type == "city":
            rows = self.fetch('SELECT lat, lon FROM cities WHERE name = ?',
                              (name,))[0]
            if rows:
                lat, lon = rows[0]
                atrs = self.fetch('''
                    SELECT atr.name FROM attractions AS atr
                    JOIN cities AS ct ON atr.city_id = ct.id
                    WHERE ct.name = ?
                ''', (name,))[0]

                html = f"<p><b>Координаты:</b> {lat}, {lon}</p>"
                html += "<p><b>Достопримечательности:</b></p><ul>"
                if atrs:
                    for row in atrs:
                        atr_name = row[0]
                        # Делаем название ссылкой
                        html += f'<li><a href="{atr_name}">{atr_name}</a></li>'
                else:
                    html += "<li>Пока не добавлены</li>"
                html += "</ul>"

                dialog = InfoDialog(self, name, html, None)
                dialog.exec()

        elif marker_type == "attraction":
            # Для достопримечательности берем описание и картинку
            rows = self.fetch('''
                SELECT description, image_name FROM attractions WHERE name = ?
            ''', (name,))[0]

            if rows:
                desc, image_name = rows[0]
                dialog = InfoDialog(self, name, desc, image_name)
                dialog.exec()

    def zoom_to_marker(self, row, column):
        table = self.sender()
        if table == self.atr_table:
            name_col, lat_col, lon_col = 2, 5, 6
            highlight = True
        else:
            name_col, lat_col, lon_col = 1, 2, 3
            highlight = False
        lat_item = table.item(row, lat_col)
        lon_item = table.item(row, lon_col)
        name_item = table.item(row, name_col)
        if not (lat_item and lon_item and name_item):
            return
        lat_tx = lat_item.text().strip()
        lon_tx = lon_item.text().strip()
        if not (lat_tx and lon_tx):
            return
        try:
            lat = float(lat_tx)
            lon = float(lon_tx)
            name = name_item.text().strip() if highlight else None

            self.main_tabs.setCurrentIndex(0)
            # Центрируем и подсвечиваем точку
            self.map.center_on(lat, lon, name)
        except ValueError:
            print("Ошибка: у этой записи битые координаты (не числа)")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = Project()
    ex.show()
    app.exec()
