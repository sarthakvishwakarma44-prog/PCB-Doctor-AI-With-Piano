import os
import sys
import json
import struct
import shutil
import tempfile
import subprocess
import cv2
import numpy as np
import serial
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from google import genai
from google.genai import types

app = FastAPI(title="PCB Doctor AI")

DEFAULT_BT_PORT = sys.argv[1] if len(sys.argv) > 1 else ""
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

def run_kicad_check(file_path: str, ext: str) -> dict:
    kicad_cli = shutil.which("kicad-cli")
    if not kicad_cli:
        return {
            "status": "error",
            "main_problem": "kicad-cli not found in system PATH.",
            "violations": []
        }

    out_json = file_path + ".report.json"
    if ext == ".kicad_sch":
        cmd = [kicad_cli, "sch", "erc", "--format", "json", "-o", out_json, file_path]
        mode = "ERC"
    elif ext == ".kicad_pcb":
        cmd = [kicad_cli, "pcb", "drc", "--format", "json", "-o", out_json, file_path]
        mode = "DRC"
    else:
        return {"status": "error", "main_problem": "Unsupported file type.", "violations": []}

    subprocess.run(cmd, capture_output=True, text=True)

    if not os.path.exists(out_json):
        return {"status": "error", "main_problem": f"KiCad {mode} failed to run.", "violations": []}

    with open(out_json, "r", encoding="utf-8") as f:
        report = json.load(f)

    violations = []
    if mode == "DRC":
        violations = report.get("violations", []) + report.get("unconnected_items", [])
    else:
        for sheet in report.get("sheets", []):
            violations.extend(sheet.get("violations", []))

    errors = [v for v in violations if v.get("severity") == "error"]
    main_problem = (
        errors[0].get("description", "Critical error detected")
        if errors else
        (violations[0].get("description", "Warning detected") if violations else f"PASS - Zero {mode} errors found")
    )

    return {
        "status": "ok",
        "mode": f"KiCad {mode}",
        "total_errors": len(errors),
        "total_warnings": len(violations) - len(errors),
        "main_problem": main_problem,
        "violations": violations[:25]
    }

def analyze_pcb_image(image_bytes: bytes) -> dict:
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        return {"status": "error", "main_problem": "Invalid image data."}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    detected_regions = sum(1 for c in contours if cv2.contourArea(c) > 150)

    if client:
        prompt = (
            "You are PCB Doctor AI. Analyze this PCB photo, component close-up, or KiCad screenshot. "
            "Return ONLY valid JSON with keys: main_problem (string), "
            "visual_drc_erc_checks (list of objects with issue, severity, fix), "
            "components (list of objects with designator_or_type, estimated_value, function)."
        )
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        try:
            ai_data = json.loads(response.text)
            ai_data["status"] = "ok"
            ai_data["opencv_regions_detected"] = detected_regions
            return ai_data
        except Exception as e:
            return {"status": "error", "main_problem": str(e)}

    return {
        "status": "offline_only",
        "opencv_regions_detected": detected_regions,
        "main_problem": "Set GEMINI_API_KEY environment variable to enable AI component and fault diagnosis.",
        "visual_drc_erc_checks": [],
        "components": []
    }

def capture_bt_frame(port: str) -> bytes:
    with serial.Serial(port, 115200, timeout=8) as ser:
        ser.reset_input_buffer()
        ser.write(b"C")
        header = ser.read(4)
        if len(header) < 4:
            raise RuntimeError("No response from Bluetooth camera.")
        size = struct.unpack("<I", header)[0]
        if size == 0 or size > 500000:
            raise RuntimeError("Invalid frame size received.")
        data = bytearray()
        while len(data) < size:
            chunk = ser.read(size - len(data))
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)

@app.post("/analyze/file")
async def analyze_file(file: UploadFile = File(...)):
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    content = await file.read()

    if ext in [".kicad_sch", ".kicad_pcb"]:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            return JSONResponse(run_kicad_check(tmp_path, ext))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    return JSONResponse(analyze_pcb_image(content))

@app.post("/analyze/bt_cam")
async def analyze_bt_cam(bt_port: str = Form(...)):
    try:
        frame = capture_bt_frame(bt_port)
        return JSONResponse(analyze_pcb_image(frame))
    except Exception as e:
        return JSONResponse({"status": "error", "main_problem": str(e)})

@app.get("/", response_class=HTMLResponse)
def home():
    html = f'''<!DOCTYPE html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PCB Doctor AI</title>
  <style>
    body {{ background:#0b0f17; color:#e2f1ff; font-family:monospace; padding:16px; max-width:900px; margin:auto; }}
    h1 {{ color:#00e5ff; border-bottom:1px solid #1e2d40; padding-bottom:8px; }}
    .card {{ background:#131b29; border:1px solid #24364d; border-radius:8px; padding:14px; margin-bottom:14px; }}
    button {{ background:#00e5ff; color:#000; border:none; padding:10px 14px; font-weight:bold; border-radius:4px; cursor:pointer; margin-top:6px; }}
    input {{ background:#0b0f17; color:#fff; border:1px solid #2e4663; padding:8px; width:70%; }}
    pre {{ background:#070a10; padding:12px; border-radius:6px; overflow-x:auto; color:#7cffb2; white-space:pre-wrap; }}
    video {{ width:100%; max-width:420px; border:1px solid #00e5ff; border-radius:6px; display:block; margin-bottom:8px; }}
  </style>
</head>
<body>
  <h1>PCB DOCTOR AI</h1>
  <div class="card">
    <h3>1. Bluetooth Camera Scan</h3>
    <input id="btPort" value="{DEFAULT_BT_PORT}" placeholder="COM5" />
    <button onclick="scanBT()">SCAN BLUETOOTH CAM</button>
  </div>
  <div class="card">
    <h3>2. Local PC / Phone Camera</h3>
    <video id="video" autoplay playsinline></video>
    <button onclick="startCam()">START CAMERA</button>
    <button onclick="captureCam()">CAPTURE & DIAGNOSE</button>
    <canvas id="canvas" style="display:none;"></canvas>
  </div>
  <div class="card">
    <h3>3. Upload PCB Screenshot or KiCad File (.kicad_sch / .kicad_pcb)</h3>
    <input type="file" id="fileInput" />
    <button onclick="uploadFile()">ANALYZE FILE</button>
  </div>
  <div class="card">
    <h3>DIAGNOSTIC OUTPUT</h3>
    <pre id="output">READY</pre>
  </div>
  <script>
    const out = document.getElementById('output');
    async function scanBT() {{
      out.textContent = "CAPTURING FROM BLUETOOTH CAMERA...";
      const fd = new FormData();
      fd.append("bt_port", document.getElementById('btPort').value);
      const res = await fetch('/analyze/bt_cam', {{ method: 'POST', body: fd }});
      out.textContent = JSON.stringify(await res.json(), null, 2);
    }}
    async function uploadFile() {{
      const f = document.getElementById('fileInput').files[0];
      if (!f) return alert("Select a file first");
      out.textContent = "ANALYZING " + f.name + "...";
      const fd = new FormData();
      fd.append("file", f);
      const res = await fetch('/analyze/file', {{ method: 'POST', body: fd }});
      out.textContent = JSON.stringify(await res.json(), null, 2);
    }}
    async function startCam() {{
      const stream = await navigator.mediaDevices.getUserMedia({{ video: {{ facingMode: "environment" }} }});
      document.getElementById('video').srcObject = stream;
    }}
    async function captureCam() {{
      const v = document.getElementById('video');
      const c = document.getElementById('canvas');
      c.width = v.videoWidth; c.height = v.videoHeight;
      c.getContext('2d').drawImage(v, 0, 0);
      out.textContent = "ANALYZING FRAME...";
      c.toBlob(async (blob) => {{
        const fd = new FormData();
        fd.append("file", blob, "webcam.jpg");
        const res = await fetch('/analyze/file', {{ method: 'POST', body: fd }});
        out.textContent = JSON.stringify(await res.json(), null, 2);
      }}, 'image/jpeg', 0.9);
    }}
  </script>
</body>
</html>'''
    return html

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
