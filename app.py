"""FastAPI backend for deterministic residential layout generation."""

import math
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from shapely.geometry import Polygon, box


# 1. Constants and illustrative rules
FT_TO_M = 0.3048
WALL_THICKNESS = 0.15
WALL_HEIGHT = 3.0
STATIC_DIR = Path(__file__).parent / "static"
RULES = {
    "label": "ILLUSTRATIVE PROTOTYPE VALUES, NOT VERIFIED REGULATIONS",
    "minimums": {
        "living": {"area": 12.0, "width": 2.7},
        "kitchen": {"area": 5.0, "width": 1.8},
        "master_bedroom": {"area": 10.0, "width": 2.7},
        "bedroom": {"area": 9.0, "width": 2.4},
        "bathroom": {"area": 3.0, "width": 1.2},
        "balcony": {"area": 2.5, "width": 1.2},
    },
    "required_adjacency": [("kitchen", "living"), ("master_bathroom", "master_bedroom")],
}
PRIORITY_WEIGHTS = {
    "light": {"adjacency": 0.15, "aspect_ratio": 0.15, "area_utilisation": 0.15, "natural_light": 0.40, "privacy": 0.15},
    "space": {"adjacency": 0.20, "aspect_ratio": 0.20, "area_utilisation": 0.40, "natural_light": 0.10, "privacy": 0.10},
    "privacy": {"adjacency": 0.25, "aspect_ratio": 0.15, "area_utilisation": 0.10, "natural_light": 0.10, "privacy": 0.40},
}
ROOM_COLORS = {
    "living": "#f4a261",
    "kitchen": "#e9c46a",
    "master_bedroom": "#8ecae6",
    "bedroom": "#90be6d",
    "bathroom": "#bde0fe",
    "balcony": "#cdb4db",
}


# 2. Data models
@dataclass
class Spec:
    """Describe the plot and generation preferences."""

    plot_w_ft: float
    plot_l_ft: float
    bhk: int
    priority: str
    seed: int


@dataclass
class Room:
    """Describe one generated room."""

    id: str
    type: str
    polygon: Polygon
    target_area: float


@dataclass
class ConstraintResult:
    """Describe one validation result."""

    constraint_id: str
    category: str
    hard: bool
    passed: bool
    elements: List[str]
    explanation: str
    suggestion: str


@dataclass
class Layout:
    """Describe a complete candidate layout."""

    seed: int
    rooms: List[Room]
    score: float = 0.0
    score_breakdown: Dict[str, float] = None
    report: List[ConstraintResult] = None


class GenerateRequest(BaseModel):
    """Validate layout generation input."""

    plot_w_ft: float = Field(30.0, gt=0)
    plot_l_ft: float = Field(50.0, gt=0)
    bhk: int = Field(3, ge=2, le=3)
    priority: str = "space"
    seed: int = 42
    candidates: int = Field(60, ge=1, le=500)


# 3. Generator
def plot_polygon(spec: Spec) -> Polygon:
    """Return the plot rectangle in metres."""
    return box(0.0, 0.0, spec.plot_w_ft * FT_TO_M, spec.plot_l_ft * FT_TO_M)


def room_definitions(bhk: int) -> List[Tuple[str, str, float]]:
    """Return room identifiers, types, and target-area fractions."""
    definitions = [
        ("living", "living", 0.24),
        ("kitchen", "kitchen", 0.10),
        ("master_bedroom", "master_bedroom", 0.15),
        ("bedroom_1", "bedroom", 0.11),
        ("bathroom_1", "bathroom", 0.045),
        ("master_bathroom", "bathroom", 0.045),
        ("balcony", "balcony", 0.04),
    ]
    if bhk == 3:
        definitions.insert(4, ("bedroom_2", "bedroom", 0.11))
        definitions.insert(6, ("bathroom_2", "bathroom", 0.045))
    return definitions


def _split_rectangle(rect: Tuple[float, float, float, float], first_area: float) -> Tuple[Tuple[float, float, float, float], Tuple[float, float, float, float]]:
    """Split a rectangle proportionally along its longer side."""
    x0, y0, x1, y1 = rect
    ratio = min(0.82, max(0.18, first_area))
    if x1 - x0 >= y1 - y0:
        cut = x0 + (x1 - x0) * ratio
        return (x0, y0, cut, y1), (cut, y0, x1, y1)
    cut = y0 + (y1 - y0) * ratio
    return (x0, y0, x1, cut), (x0, cut, x1, y1)


def _bsp(rect: Tuple[float, float, float, float], rooms: List[Tuple[str, str, float]], plot_area: float) -> List[Room]:
    """Recursively assign proportional rectangles to rooms."""
    if len(rooms) == 1:
        room_id, room_type, fraction = rooms[0]
        return [Room(room_id, room_type, box(*rect), plot_area * fraction)]
    left_count = 1 if len(rooms) == 2 else 2
    left, right = rooms[:left_count], rooms[left_count:]
    total = sum(item[2] for item in rooms)
    first_area = sum(item[2] for item in left) / total
    rect_a, rect_b = _split_rectangle(rect, first_area)
    return _bsp(rect_a, left, plot_area) + _bsp(rect_b, right, plot_area)


def _candidate_order(definitions: List[Tuple[str, str, float]], rng: random.Random) -> List[Tuple[str, str, float]]:
    """Shuffle non-required rooms while preserving required adjacency clusters."""
    living_cluster = [item for item in definitions if item[0] in {"living", "kitchen"}]
    master_cluster = [item for item in definitions if item[0] in {"master_bedroom", "master_bathroom"}]
    others = [item for item in definitions if item[0] not in {"living", "kitchen", "master_bedroom", "master_bathroom"}]
    rng.shuffle(others)
    return living_cluster + master_cluster + others


def generate_candidates(spec: Spec, n: int = 60) -> List[Layout]:
    """Generate deterministic BSP layout candidates."""
    rng = random.Random(spec.seed)
    definitions = room_definitions(spec.bhk)
    plot = plot_polygon(spec)
    candidates = []
    for index in range(n):
        candidate_rng = random.Random(rng.randint(0, 2**31 - 1))
        rooms = _bsp((0.0, 0.0, plot.bounds[2], plot.bounds[3]), _candidate_order(definitions, candidate_rng), plot.area)
        candidates.append(Layout(spec.seed + index, rooms))
    return candidates


# 4. Validator
def _minimum_width(polygon: Polygon) -> float:
    """Return the smaller axis-aligned side of a room polygon."""
    min_x, min_y, max_x, max_y = polygon.bounds
    return min(max_x - min_x, max_y - min_y)


def _adjacent(first: Room, second: Room) -> bool:
    """Return whether two rooms share at least the required boundary."""
    return first.polygon.boundary.intersection(second.polygon.boundary).length >= 0.9 - 1e-9


def validate(layout: Layout, plot: Polygon) -> List[ConstraintResult]:
    """Validate geometric, spatial, and dimensional constraints."""
    results = []
    for room in layout.rooms:
        minimum = RULES["minimums"][room.type]
        inside = plot.covers(room.polygon)
        valid = room.polygon.is_valid
        area_ok = room.polygon.area + 1e-9 >= minimum["area"]
        width_ok = _minimum_width(room.polygon) + 1e-9 >= minimum["width"]
        results.extend([
            ConstraintResult(f"inside_{room.id}", "geometric", True, inside, [room.id], "Room is inside the plot." if inside else "Room extends outside the plot.", "Keep every room within the plot boundary."),
            ConstraintResult(f"valid_{room.id}", "geometric", True, valid, [room.id], "Room polygon is valid." if valid else "Room polygon is invalid.", "Regenerate the room polygon."),
            ConstraintResult(f"area_{room.id}", "dimensional", True, area_ok, [room.id], f"Area is {room.polygon.area:.2f} m2; minimum is {minimum['area']:.2f} m2.", "Increase the room area."),
            ConstraintResult(f"width_{room.id}", "dimensional", True, width_ok, [room.id], f"Minimum side is {_minimum_width(room.polygon):.2f} m; minimum is {minimum['width']:.2f} m.", "Increase the narrowest room dimension."),
        ])
    for index, first in enumerate(layout.rooms):
        for second in layout.rooms[index + 1:]:
            passed = first.polygon.intersection(second.polygon).area <= 1e-6
            results.append(ConstraintResult(f"overlap_{first.id}_{second.id}", "geometric", True, passed, [first.id, second.id], "Rooms do not overlap." if passed else "Rooms overlap.", "Regenerate with non-overlapping rectangles."))
    for first_type, second_type in RULES["required_adjacency"]:
        first = next((room for room in layout.rooms if room.id == first_type or room.type == first_type), None)
        second = next((room for room in layout.rooms if room.id == second_type or room.type == second_type), None)
        passed = first is not None and second is not None and _adjacent(first, second)
        results.append(ConstraintResult(f"adjacency_{first_type}_{second_type}", "spatial", True, passed, [room.id for room in (first, second) if room], "Required adjacency is met." if passed else "Required adjacency is missing.", "Place the required rooms on a shared boundary of at least 0.9 m."))
    return results


# 5. Scorer
def score(layout: Layout, spec: Spec) -> Tuple[float, Dict[str, float]]:
    """Score a valid layout from zero to one hundred."""
    plot = plot_polygon(spec)
    living = next(room for room in layout.rooms if room.type == "living")
    balcony = next(room for room in layout.rooms if room.type == "balcony")
    kitchen = next(room for room in layout.rooms if room.type == "kitchen")
    bathrooms = [room for room in layout.rooms if room.type == "bathroom"]
    adjacency = 1.0 if _adjacent(living, balcony) else 0.5
    if any(_adjacent(kitchen, bathroom) for bathroom in bathrooms):
        adjacency -= 0.25
    aspect_values = []
    for room in layout.rooms:
        width = room.polygon.bounds[2] - room.polygon.bounds[0]
        height = room.polygon.bounds[3] - room.polygon.bounds[1]
        ratio = max(width, height) / max(min(width, height), 1e-9)
        aspect_values.append(1.0 if ratio <= 2.5 else max(0.0, 1.0 - (ratio - 2.5) / 2.5))
    aspect_ratio = float(np.mean(aspect_values))
    area_utilisation = min(1.0, sum(room.polygon.area for room in layout.rooms) / plot.area / 0.95)
    light = float(np.mean([
        min(1.0, room.polygon.boundary.intersection(plot.boundary).length / max(room.polygon.boundary.length, 1e-9) * (1.15 if room.type in {"living", "master_bedroom", "bedroom"} else 1.0))
        for room in layout.rooms
    ]))
    bedrooms = [room for room in layout.rooms if room.type in {"master_bedroom", "bedroom"}]
    max_distance = math.hypot(plot.bounds[2], plot.bounds[3])
    privacy = min(1.0, float(np.mean([living.polygon.centroid.distance(room.polygon.centroid) / max_distance for room in bedrooms])) * 2.0)
    breakdown = {"adjacency": adjacency, "aspect_ratio": aspect_ratio, "area_utilisation": area_utilisation, "natural_light": light, "privacy": privacy}
    weights = PRIORITY_WEIGHTS[spec.priority]
    total = sum(breakdown[key] * weights[key] for key in breakdown) * 100.0
    return round(total, 2), {key: round(value, 3) for key, value in breakdown.items()}


def top_layouts(candidates: List[Layout], spec: Spec, plot: Polygon) -> Tuple[List[Layout], Dict[str, int]]:
    """Validate, score, and return the top three candidates."""
    rejected = {}
    valid_layouts = []
    for layout in candidates:
        layout.report = validate(layout, plot)
        failures = [result for result in layout.report if result.hard and not result.passed]
        if failures:
            for result in failures:
                rejected[result.constraint_id] = rejected.get(result.constraint_id, 0) + 1
            continue
        layout.score, layout.score_breakdown = score(layout, spec)
        valid_layouts.append(layout)
    valid_layouts.sort(key=lambda item: (-item.score, item.seed))
    return valid_layouts[:3], rejected


# 6. API serialization and frontend data
def _room_json(room: Room) -> Dict:
    """Serialize a room polygon for the frontend."""
    return {"id": room.id, "type": room.type, "target_area": room.target_area, "area": round(room.polygon.area, 3), "polygon": list(room.polygon.exterior.coords), "color": ROOM_COLORS[room.type]}


def _cuboid(bounds: Tuple[float, float, float, float, float, float]) -> Dict:
    """Return Plotly-compatible cuboid mesh data."""
    x0, y0, z0, x1, y1, z1 = bounds
    vertices = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 4, 5), (0, 5, 1), (1, 5, 6), (1, 6, 2), (2, 6, 7), (2, 7, 3), (3, 7, 4), (3, 4, 0)]
    return {"x": [point[0] for point in vertices], "y": [point[1] for point in vertices], "z": [point[2] for point in vertices], "i": [face[0] for face in faces], "j": [face[1] for face in faces], "k": [face[2] for face in faces]}


def _layout_json(layout: Layout, spec: Spec) -> Dict:
    """Serialize a layout including 2D and 3D geometry."""
    meshes = []
    for room in layout.rooms:
        x0, y0, x1, y1 = room.polygon.bounds
        meshes.append({**_cuboid((x0, y0, 0, x1, y1, 0.08)), "name": f"{room.id} floor", "color": ROOM_COLORS[room.type]})
        edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
        for edge_index, ((ax, ay), (bx, by)) in enumerate(edges):
            angle = math.atan2(by - ay, bx - ax)
            cx, cy = (ax + bx) / 2, (ay + by) / 2
            half_length, half_width = math.hypot(bx - ax, by - ay) / 2, WALL_THICKNESS / 2
            corners = [(cx - half_length, cy - half_width), (cx + half_length, cy - half_width), (cx + half_length, cy + half_width), (cx - half_length, cy + half_width)]
            rotated = [(cx + (px - cx) * math.cos(angle) - (py - cy) * math.sin(angle), cy + (px - cx) * math.sin(angle) + (py - cy) * math.cos(angle)) for px, py in corners]
            meshes.append({**_cuboid((min(point[0] for point in rotated), min(point[1] for point in rotated), 0.08, max(point[0] for point in rotated), max(point[1] for point in rotated), WALL_HEIGHT)), "name": f"{room.id} wall {edge_index + 1}", "color": ROOM_COLORS[room.type]})
    return {"seed": layout.seed, "score": layout.score, "score_breakdown": layout.score_breakdown, "rooms": [_room_json(room) for room in layout.rooms], "report": [asdict(result) for result in layout.report], "meshes": meshes}


# 7. FastAPI application
app = FastAPI(title="Interior Layout API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
def serve_frontend() -> Path:
    """Serve the React frontend."""
    return STATIC_DIR / "index.html"


@app.get("/api/health")
def health() -> Dict[str, str]:
    """Return backend health."""
    return {"status": "ok"}


@app.post("/api/generate")
def generate(request: GenerateRequest) -> Dict:
    """Generate and return the top valid layouts."""
    if request.priority not in PRIORITY_WEIGHTS:
        raise HTTPException(status_code=422, detail="priority must be light, space, or privacy")
    spec = Spec(request.plot_w_ft, request.plot_l_ft, request.bhk, request.priority, request.seed)
    plot = plot_polygon(spec)
    minimum_area = sum(RULES["minimums"][room_type]["area"] for _, room_type, _ in room_definitions(spec.bhk))
    if minimum_area > plot.area:
        raise HTTPException(status_code=422, detail=f"Minimum room area is {minimum_area:.2f} m2; plot area is {plot.area:.2f} m2.")
    layouts, rejected = top_layouts(generate_candidates(spec, request.candidates), spec, plot)
    return {"spec": asdict(spec), "plot": {"width_m": plot.bounds[2], "length_m": plot.bounds[3], "width_ft": spec.plot_w_ft, "length_ft": spec.plot_l_ft}, "rules_label": RULES["label"], "layouts": [_layout_json(layout, spec) for layout in layouts], "candidate_count": request.candidates, "valid_count": len(layouts), "rejected_by_constraint": rejected}


# 8. Self-tests
def run_self_tests() -> None:
    """Run focused deterministic validation tests."""
    spec = Spec(30, 50, 2, "space", 42)
    plot = plot_polygon(spec)
    layouts, _ = top_layouts(generate_candidates(spec, 10), spec, plot)
    assert layouts
    first = generate_candidates(spec, 5)
    second = generate_candidates(spec, 5)
    assert [(item.seed, [(room.id, room.polygon.bounds) for room in item.rooms]) for item in first] == [(item.seed, [(room.id, room.polygon.bounds) for room in item.rooms]) for item in second]
    assert any(not item.passed for item in validate(Layout(1, [Room("living", "living", box(-1, 0, 5, 4), 20)]), plot) if item.constraint_id == "inside_living")
    assert any(not item.passed for item in validate(Layout(2, [Room("living", "living", box(0, 0, 5, 4), 20), Room("kitchen", "kitchen", box(4, 0, 7, 4), 12)]), plot) if item.constraint_id == "overlap_living_kitchen")
    print("Self-tests passed.")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_self_tests()
