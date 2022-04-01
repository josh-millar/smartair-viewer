import os
import random
import re
import urllib

import dash

import dash_bootstrap_components as dbc
from dash import html
from dash import dcc

from dash.dependencies import Input, Output, State

import dash_vtk
from dash_vtk.utils import to_mesh_state, preset_as_options

import vtk
import flask


class Viz:
    """Main visualisation class to define the vtk pipeline
    of a given cfd simulation. In the context of smartair,
    this will generally be used to create an instance of
    a viewer for each floor
    """

    def __init__(self):
        """
        Initialises the Viz class with correct locations for
        post-processing data
        """
        self.case_directory = ""

        # dict to map the desired fields to their primitive fields, and
        # define the corresponding colorbar
        self.fields_dict = {
            "ACH": ["AoA", "Black, Blue and White"],
            "FAR": ["AoA", "Viridis (matplotlib)"],
            "CO2": ["CO2", "Cool to Warm"],
            "U": ["U", "Rainbow Desaturated"],
        }

    def getgeomrepresenation(self, stl_name, opacity=1.0):
        """
        Creates the visulisation for an arbitrary stl

        Parameters
        ----------
        stl_name: str
            Name of the stl to display, as wrtten in the simulation
            e.g. "walls"
        opacity: float, optional
            Opacity to view the stl as, default 1.0
        Returns
        -------
        geom_representation: dash_vtk.GeometryRepresentation.GeometryRepresentation
            The geometry representation of the stls for viewing inside a
            dash_vtk.View.
        edges_representation: dash_vtk.GeometryRepresentation.GeometryRepresentation
            The geometry representation for viewing inside a
            dash_vtk.View.
        """

        geom_filename = os.path.join(
            self.case_directory, "constant/triSurface/" + stl_name + ".stl"
        )
        # read the stl and convert to a vtkPolyData:
        geom_reader = vtk.vtkSTLReader()
        geom_reader.SetFileName(geom_filename)
        geom_reader.Update()
        full_geom_data = geom_reader.GetOutput()
        # note, this currently only works for constant heights,
        # in practice this should be changed to use the mode
        self.ceiling_height = full_geom_data.GetBounds()[5]
        # clip the vtkPolyData and convert to mesh:
        clip_height = self.ceiling_height - 0.1
        plane = vtk.vtkPlane()
        plane.SetNormal(0, 0, -1)
        plane.SetOrigin(0, 0, clip_height)
        clipper = vtk.vtkClipPolyData()
        clipper.SetInputData(full_geom_data)
        clipper.SetClipFunction(plane)
        clipper.Update()
        geom_mesh = to_mesh_state(clipper.GetOutput())

        # get feature edges
        fedges = vtk.vtkFeatureEdges()
        fedges.SetInputData(clipper.GetOutput())
        fedges.Update()
        fedges_mesh = to_mesh_state(fedges.GetOutput())

        # create the geometry representations to return to the
        # viewer
        geom_representation = dash_vtk.GeometryRepresentation(
            property={"color": [1, 1, 1], "opacity": opacity, "ambient": 0.3},
            children=[
                dash_vtk.Mesh(id=stl_name, state=geom_mesh),
            ],
        )

        edges_representation = dash_vtk.GeometryRepresentation(
            property={"color": [0, 0, 0], "opacity": opacity},
            children=[
                dash_vtk.Mesh(id=stl_name + "edges", state=fedges_mesh),
            ],
        )

        return geom_representation, edges_representation

    def getcontourrepresentation(self, field, inlet_air):
        """
        Creates the visulisation for an arbitrary stl

        Parameters
        ----------
        field: str
            Name of the stl to display, as wrtten in the simulation
            e.g. "walls"
        opacity: float, optional
            Opacity to view the stl as, default 1.0
        Returns
        -------
        geom_representation: dash_vtk.GeometryRepresentation
            The geometry representation of the stls for viewing inside a
            dash_vtk.View.
        edges_representation: dash_vtk.GeometryRepresentation
            The geometry representation for viewing inside a
            dash_vtk.View.
        """
        # select the correct properties for the outfield requested
        in_field = self.fields_dict[field][0]
        colormap = self.fields_dict[field][1]

        def findlatesttime(self, postprocdir):
            """Helper to get the correct post-processing files"""
            max_dir = 0
            for path in os.listdir(postprocdir):
                if int(path) > max_dir:
                    max_dir = int(path)

            return str(max_dir)

        self.post_proc_directory = os.path.join(
            self.case_directory, "postProcessing", "surfaces"
        )
        self.surfaces_directory = os.path.join(
            self.post_proc_directory, findlatesttime(self, self.post_proc_directory)
        )

        in_field_file = os.path.join(
            self.surfaces_directory, in_field + "_surfaces0.vtk"
        )

        # convert plane to a vtkpolymesh
        plane_reader = vtk.vtkPolyDataReader()
        plane_reader.SetFileName(in_field_file)
        plane_reader.ReadAllVectorsOn()
        plane_reader.Update()
        plane_data = plane_reader.GetOutput()

        # post process to obtain display field
        if field == "ACH":
            out_data = self.computeACH(plane_data, inlet_air=inlet_air)
        elif field == "FAR":
            out_data = self.computeFAR(plane_data, inlet_air=inlet_air)
        else:
            out_data = plane_data

        plane_mesh = to_mesh_state(out_data, field_to_keep=field)

        plane_representation = dash_vtk.GeometryRepresentation(
            colorMapPreset=colormap,
            colorDataRange=[0, 2],
            mapper={
                "colorByArrayName": field,
                "scalarMode": 0,
                "interpolateScalarsBeforeMapping": True,
                "useInvertibleColors": True,
            },
            property={"ambient": 0.3},
            children=[
                dash_vtk.Mesh(state=plane_mesh),
            ],
        )
        print(field)
        return plane_representation

    def computeACH(self, plane_data, inlet_air=0.10):
        """Computes the fresh air changes hourly as
        fACH = 3600 / AoA * inlet_air
         Parameters
        ----------
        plane_data: vtkPolyData
            Name of the stl to display, as wrtten in the simulation
            e.g. "walls"
        inlet_air: float, optional
            The baseline value of the inlet air
        Returns
        -------
        out_data: vtkPolyData
            The output data to display to the viewer
        """
        calculator = vtk.vtkArrayCalculator()
        calculator.SetInputData(plane_data)
        calculator.AddScalarArrayName("AoA")
        calculator.SetFunction("3600 / {} * {}".format("AoA", str(inlet_air)))
        calculator.SetResultArrayName("ACH")
        calculator.Update()

        return calculator.GetOutput()

    def computeFAR(self, plane_data, inlet_air=0.10):
        """Computes the local fresh air rate defined as:
        FAR = FAI * inlet_flow_rate * inlet_air
        where FAI is the ratio of volumetric mean AoA to measured AoA
         Parameters
        ----------
        plane_data: vtkPolyData
            Name of the stl to display, as wrtten in the simulation
            e.g. "walls"
        inlet_air: float, optional
            The baseline value of the inlet air
        Returns
        -------
        out_data: vtkPolyData
            The output data to display to the viewer
        """
        # compute scalars:
        properties = vtk.vtkMassProperties()
        properties.SetInputData(plane_data)
        plane_area = properties.GetSurfaceArea()
        volume = plane_area * self.ceiling_height
        self.total_flow = self.gettotalflowrate()
        AoA_mean = volume / (self.total_flow * 0.001)
        # compute FAI, FAR fields
        calculator = vtk.vtkArrayCalculator()
        calculator.SetInputData(plane_data)
        calculator.AddScalarArrayName("AoA")
        calculator.SetFunction("{} / {}".format(str(AoA_mean), "AoA"))
        calculator.SetResultArrayName("FAI")
        calculator.Update()
        calculator2 = vtk.vtkArrayCalculator()
        calculator2.SetInputData(calculator.GetOutput())
        calculator2.AddScalarArrayName("FAI")
        calculator2.SetFunction(
            "{} * {} * {}".format("FAI", str(self.total_flow * 0.001), str(inlet_air))
        )
        calculator2.SetResultArrayName("FAR")
        calculator2.Update()

        return calculator2.GetOutput()

    def gettotalflowrate(self):
        """Computes total flow rate in L/s based on the naming convention
        of the supply patches in constant/triSurface
        """
        total_flow = 0
        trisurface_dir = os.path.join(self.case_directory, "constant", "triSurface")
        supply_files = [
            filename
            for filename in os.listdir(trisurface_dir)
            if filename.startswith("supply")
        ]
        for supply in supply_files:
            flowrate = re.findall("_(\d+).stl", supply)
            total_flow += float(flowrate[0])

        return total_flow


# initialise the app and the visualisation instance:
FA = "https://use.fontawesome.com/releases/v5.15.1/css/all.css"
app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.LUX, FA]
)
server = app.server
vis = Viz()

sidebar = html.Div(
    [
        dcc.Location(id="url", refresh=False),
        html.Div(
            [
                html.Img(src=app.get_asset_url("wsp_logo.png"), style={"width": "3rem"}, className="wsp_logo"),
                html.Img(src=app.get_asset_url("smartair_logo.png"), style={"width": "80%"}),
            ],
            className="sidebar-header",
        ),
        html.Hr(),
        dbc.Nav(
            [
                 dbc.NavLink(
                    [
                        html.I(className="fas fa-cogs", style={"width": "3rem"})
                    ]
                ),
                dbc.CardBody(
                [
                    html.H5(
                        [
                                "Analysis name: ",
                            html.Span(
                                id="analysis_name",
                                # style={"display": "inline-block", "margin-left": "5px"},
                            ),
                        ],
                    ),
                    html.Div(
                        children=[
                            html.Label("Level:"),
                            dcc.Dropdown(
                                id="levels",
                                style={"margin-left": "5px", "width": "50%"},
                            ),
                        ],
                    ),
                    html.Br(),
                    html.Br(),
                    html.P("Select visualisation field: "),
                    dcc.Dropdown(
                        ["U", "FAR", "ACH"], "U", id="vis_field", style={"width": "50%"}
                    ),
                    html.Br(),
                    html.Div(
                        children=[
                            html.H5("Fresh air: ", style={"display": "inline-block"}),
                            html.Span(
                                id="fresh_air_value", style={"display": "inline-block"}
                            ),
                        ],
                    ),
                    html.Br(),
                    dcc.Slider(
                        id="fresh-air",
                        min=0,
                        max=20,
                        step=1,
                        value=10,
                        marks={0: "0%", 5: "5%", 10: "10%", 15: "15%", 20: "20%"},
                    ),
                ],
                className="sidebar-content"
            )
        ]),
    ],
    className="sidebar"
)


content = html.Div(id="vtk_vis", className="content", style={"width": "100%", "height": "calc(100vh - 30px)"})
app.layout = html.Div([sidebar, content])

@app.callback(
    [
        Output("analysis_name", "children"),
        Output("levels", "options"),
        Output("levels", "value"),
    ],
    Input("url", "search"),
    prevent_initial_callback=True,
)
def getlevels(search):
    """this function is called upon loading the page
    and collects the
    """
    parsed = urllib.parse.urlparse(search)
    try:
        case = parsed.query.split("=")[1]
        path_prefix = "/mnt/cfdrun/smartair/dash/"
        levels = [
            level
            for level in os.listdir(os.path.join(path_prefix, case))
            if level.startswith("level")
        ]
        value = levels[0]
    except:
        case = "No analysis specified in url"
    return case, levels, value


# now can display now that we know the working dir
@app.callback(
    Output("vtk_vis", "children"),
    Output("fresh_air_value", "children"),
    Input("vis_field", "value"),
    Input("levels", "value"),
    Input("fresh-air", "value"),
    State("url", "search"),
    prevent_initial_callback=True,
)
def updatecasedir(vis_value, level_value, fresh_air_value, search):
    parsed = urllib.parse.urlparse(search)
    case = parsed.query.split("=")[1]
    path_prefix = "./"
    case_dir = os.path.join(path_prefix, case, level_value)
    vis.case_directory = os.path.join(path_prefix, case, level_value)
    geom, edges = vis.getgeomrepresenation("walls")
    visplane = vis.getcontourrepresentation(vis_value, fresh_air_value * 0.01)
    vtk_vis = dash_vtk.View(background=[1, 1, 1], children=[geom, edges, visplane])
    fresh_air_percent = str(fresh_air_value) + "%"

    return vtk_vis, fresh_air_percent


if __name__ == "__main__":
    app.run_server(debug=True, port=8000)
