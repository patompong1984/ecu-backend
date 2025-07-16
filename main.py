from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route("/analyze", methods=["POST"])
def analyze_bin():
    bin_file = request.files['bin']
    content = bin_file.read()

    offset = 0x1D8710
    block = content[offset : offset + 256]
    map_2d = []

    for i in range(16):
        row = block[i*16 : (i+1)*16]
        scaled = [round(b * 0.05, 2) for b in row]
        map_2d.append(scaled)

    return jsonify({ "map": map_2d })

if __name__ == "__main__":
    app.run()
