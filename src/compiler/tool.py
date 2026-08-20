import math
from src.db.models import Tool

class VBitTool:
    def __init__(self, tool_data: Tool):
        self.tool_data = tool_data
        self.angle_deg = tool_data.angle_deg
        self.tip_diameter = tool_data.tip_diameter
        self.depth = abs(tool_data.depth)

    @property
    def offset_radius(self) -> float:
        angle_rad = math.radians(self.angle_deg / 2.0)
        r_eff = (self.tip_diameter / 2.0) + (self.depth * math.tan(angle_rad))
        return r_eff