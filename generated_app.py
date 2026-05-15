from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Card, CardContent, CardHeader, CardTitle,
    Column, H1, H2, H3, Muted, Tab, Tabs, Text,
)

with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:
    with Card():
        with CardHeader():
            CardTitle('Camera & Lens Calculator')
        with CardContent():
            with Tabs(value='inputs'):
                with Tab('Inputs', value='inputs'):
                    with Column(gap=5):
                        with Column(gap=1):
                            H3('Latest step')
                            Muted('Iteration 2')
                        with Column(gap=1):
                            H2('Calculate Pixels Per Mm')
                            Muted('Values update after each optics MCP tool call.')
                        with Column(gap=1):
                            Muted('Working distance (mm)')
                            H1('500.0')
                        with Column(gap=1):
                            Muted('Sensor width (px)')
                            H1('2144')
                        with Column(gap=1):
                            Muted('Focal length (mm)')
                            H1('13.803')
                        with Column(gap=1):
                            Muted('FOV (degrees)')
                            H1('30.0')
                        with Column(gap=1):
                            Muted('Pixel pitch (µm)')
                            H1('3.45')
                        with Column(gap=1):
                            Muted('Sensor height (px)')
                            H1('1608')
                with Tab('Results', value='results'):
                    with Column(gap=5):
                        with Column(gap=1):
                            Muted('Pixels / mm (horizontal)')
                            H1('8.0015')
                        with Column(gap=1):
                            Muted('Mm / pixel (horizontal)')
                            H1('0.124976')
                        with Column(gap=1):
                            Muted('Object FOV width (mm)')
                            H1('267.949')
                        with Column(gap=1):
                            Muted('Sensor width (mm)')
                            H1('7.397')
                        with Column(gap=1):
                            Muted('Pixels / mm (vertical)')
                            H1('8.0015')
                        with Column(gap=1):
                            Muted('Mm / pixel (vertical)')
                            H1('0.124976')
                        with Column(gap=1):
                            Muted('Object FOV height (mm)')
                            H1('200.962')
