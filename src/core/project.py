import json
from pathlib import Path
from shapely import wkt
from src.parser.geometry import CamPath

class ProjectState:
    def __init__(self):
        self.input_filepath = None
        self.current_project_dir = None
        
        self.raw_paths = []
        self.ready_paths = []
        self.distorted_paths = []
        self.mask_geom = None 
        
        self.is_array_layout = False
        self.array_offsets = []      
        self.master_raw_paths = []   
        
        self.layers = {"raw": [], "healed": [], "array": [], "distorted": [], "mask": [], "ideal": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.is_distorted = False
        self.applied_dist_axis = ""
        self.current_rapport = 0.0
        self.current_dist_factor = 1.0
        self.layout_mismatch = False
        self.layout_len_val = 0.0
        self.last_milling_time_min = 0.0

    def reset_data(self):
        self.raw_paths = []
        self.ready_paths = []
        self.distorted_paths = []
        self.mask_geom = None
        
        self.is_array_layout = False
        self.array_offsets = []
        self.master_raw_paths = []
        
        self.layers = {"raw": [], "healed": [], "array": [], "distorted": [], "mask": [], "ideal": [], "cnc": []}
        self.error_markers = {"red": [], "orange": [], "magenta": [], "yellow": []}
        
        self.is_distorted = False
        self.applied_dist_axis = ""
        self.layout_mismatch = False
        self.layout_len_val = 0.0
        self.last_milling_time_min = 0.0

    def to_dict(self, ui_data: dict) -> dict:
        return {
            "input_filepath": str(self.input_filepath) if self.input_filepath else None,
            "last_milling_time_min": self.last_milling_time_min,
            "ui": ui_data,
            "flags": {
                "is_array_layout": self.is_array_layout,
                "array_offsets": self.array_offsets,
                "is_distorted": self.is_distorted,
                "applied_dist_axis": self.applied_dist_axis
            },
            "paths": {
                "raw_paths": [p.to_dict() for p in self.raw_paths],
                "ready_paths": [p.to_dict() for p in self.ready_paths],
                "distorted_paths": [p.to_dict() for p in self.distorted_paths],
                "master_raw_paths": [p.to_dict() for p in self.master_raw_paths],
            },
            "layers": {
                "raw": [p.to_dict() for p in self.layers.get("raw", [])],
                "healed": [p.to_dict() for p in self.layers.get("healed", [])],
                "array": [p.to_dict() for p in self.layers.get("array", [])],
                "distorted": [p.to_dict() for p in self.layers.get("distorted", [])],
                "mask": [p.to_dict() for p in self.layers.get("mask", [])],
                "ideal": [p.to_dict() for p in self.layers.get("ideal", [])],
                "cnc": [p.to_dict() for p in self.layers.get("cnc", [])]
            },
            "mask_geom_wkt": self.mask_geom.wkt if self.mask_geom else None
        }

    def from_dict(self, data: dict):
        self.input_filepath = Path(data["input_filepath"]) if data.get("input_filepath") else None
        self.last_milling_time_min = data.get("last_milling_time_min", 0.0)
        
        flags = data.get("flags", {})
        self.is_array_layout = flags.get("is_array_layout", False)
        self.array_offsets = [tuple(o) for o in flags.get("array_offsets", [])]
        self.is_distorted = flags.get("is_distorted", False)
        self.applied_dist_axis = flags.get("applied_dist_axis", "")
        
        paths_data = data.get("paths", {})
        self.raw_paths = [CamPath.from_dict(p) for p in paths_data.get("raw_paths", [])]
        self.ready_paths = [CamPath.from_dict(p) for p in paths_data.get("ready_paths", [])]
        self.distorted_paths = [CamPath.from_dict(p) for p in paths_data.get("distorted_paths", [])]
        self.master_raw_paths = [CamPath.from_dict(p) for p in paths_data.get("master_raw_paths", [])]
        
        layers_data = data.get("layers", {})
        self.layers = {
            "raw": [CamPath.from_dict(p) for p in layers_data.get("raw", [])],
            "healed": [CamPath.from_dict(p) for p in layers_data.get("healed", [])],
            "array": [CamPath.from_dict(p) for p in layers_data.get("array", [])],
            "distorted": [CamPath.from_dict(p) for p in layers_data.get("distorted", [])],
            "mask": [CamPath.from_dict(p) for p in layers_data.get("mask", [])],
            "ideal": [CamPath.from_dict(p) for p in layers_data.get("ideal", [])],
            "cnc": [CamPath.from_dict(p) for p in layers_data.get("cnc", [])]
        }
        
        mask_wkt = data.get("mask_geom_wkt")
        if mask_wkt: self.mask_geom = wkt.loads(mask_wkt)
        else: self.mask_geom = None