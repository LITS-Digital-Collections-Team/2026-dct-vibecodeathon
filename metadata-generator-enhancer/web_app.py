"""
Flask web interface for Archipelago Metadata Generator & Enhancer
Run: python web_app.py
Then open http://localhost:5000 in your browser
"""

from flask import Flask, render_template, request, jsonify, send_file
import os
import json
from pathlib import Path
from werkzeug.utils import secure_filename
from generator import MetadataGenerator
from validator import MetadataValidator
import io
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'output'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Create folders if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# Initialize backend
generator = MetadataGenerator()
validator = MetadataValidator()

# Log messages for real-time updates
logs = []

def add_log(message, level="info"):
    """Add message to log"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {
        "timestamp": timestamp,
        "message": message,
        "level": level
    }
    logs.append(log_entry)
    print(f"[{timestamp}] {message}")

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/logs')
def get_logs():
    """Get all logs"""
    return jsonify(logs)

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    """Clear logs"""
    global logs
    logs = []
    return jsonify({"status": "success"})

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handle file upload"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if not file.filename.endswith(('.csv', '.json')):
            return jsonify({"error": "Only CSV and JSON files are supported"}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Try to load the file
        try:
            if filename.endswith('.csv'):
                records = generator.load_from_csv(filepath)
            else:
                records = generator.load_from_json(filepath)
            
            add_log(f"✓ File uploaded: {filename} ({len(records)} records)", "success")
            
            return jsonify({
                "status": "success",
                "filename": filename,
                "records": len(records),
                "filepath": filepath
            })
        except Exception as e:
            add_log(f"✗ Error loading file: {str(e)}", "error")
            return jsonify({"error": f"Error loading file: {str(e)}"}), 400
            
    except Exception as e:
        add_log(f"✗ Upload error: {str(e)}", "error")
        return jsonify({"error": str(e)}), 500

@app.route('/api/process', methods=['POST'])
def process_file():
    """Process metadata file"""
    try:
        data = request.json
        filepath = data.get('filepath')
        output_format = data.get('format', 'both')
        enhance = data.get('enhance', True)
        normalize_names = data.get('normalize_names', False)
        validate = data.get('validate', True)
        
        # Handle both full paths and relative paths
        if not filepath.startswith('/'):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filepath.split('/')[-1])
        else:
            # If it's an absolute path from the client, just use the filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(filepath))
        
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 400
        
        add_log(f"\n{'='*60}", "info")
        add_log(f"Processing file: {Path(filepath).name}", "info")
        add_log(f"{'='*60}", "info")
        
        # Load file
        add_log("Loading file...", "info")
        if filepath.endswith('.csv'):
            records = generator.load_from_csv(filepath)
        else:
            records = generator.load_from_json(filepath)
        
        add_log(f"✓ Loaded {len(records)} records", "success")
        
        # Enhance if requested
        if enhance:
            add_log("Enhancing records...", "info")
            options = {
                'fill_defaults': True,
                'normalize_names': normalize_names,
            }
            generator.enhance_batch(options=options)
            add_log("✓ Records enhanced", "success")
        
        # Export
        basename = Path(filepath).stem
        output_files = []
        
        if output_format in ['csv', 'both']:
            add_log("Exporting to CSV...", "info")
            csv_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{basename}_output.csv')
            result = generator.to_csv(csv_path, validate=validate)
            add_log(f"✓ CSV exported: {Path(csv_path).name}", "success")
            output_files.append(csv_path)
            
            if result.get('validation_summary'):
                summary = result['validation_summary']
                add_log(f"  Valid: {summary['valid']}/{summary['total']} records", "info")
        
        if output_format in ['json', 'both']:
            add_log("Exporting to JSON...", "info")
            json_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{basename}_output.json')
            result = generator.to_json(json_path, validate=validate)
            add_log(f"✓ JSON exported: {Path(json_path).name}", "success")
            output_files.append(json_path)
        
        add_log("✓ Processing complete!", "success")
        
        return jsonify({
            "status": "success",
            "output_files": [Path(f).name for f in output_files]
        })
        
    except Exception as e:
        add_log(f"✗ Error: {str(e)}", "error")
        return jsonify({"error": str(e)}), 500

@app.route('/api/validate', methods=['POST'])
def validate_file():
    """Validate metadata file"""
    try:
        data = request.json
        filepath = data.get('filepath')
        
        # Handle both full paths and relative paths
        if not filepath.startswith('/'):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filepath.split('/')[-1])
        else:
            # If it's an absolute path from the client, just use the filename
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(filepath))
        
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 400
        
        add_log(f"\n{'='*60}", "info")
        add_log(f"Validating file: {Path(filepath).name}", "info")
        add_log(f"{'='*60}", "info")
        
        # Load records
        add_log("Loading file...", "info")
        if filepath.endswith('.csv'):
            records = generator.load_from_csv(filepath)
        else:
            records = generator.load_from_json(filepath)
        
        add_log(f"✓ Loaded {len(records)} records\n", "success")
        
        # Validate
        add_log("Validating records against schema...", "info")
        summary = validator.validate_batch(records)
        
        # Display results
        add_log("", "info")
        add_log("Validation Results:", "info")
        add_log(f"  Total records: {summary['total']}", "info")
        add_log(f"  Valid records: {summary['valid']}", "success")
        add_log(f"  Invalid records: {summary['invalid']}", 
               "warning" if summary['invalid'] > 0 else "success")
        
        if summary['invalid'] > 0:
            add_log("", "info")
            add_log("Errors found:", "warning")
            for idx, errors in list(summary.get('error_details', {}).items())[:5]:
                add_log(f"  Record {idx}: {errors}", "warning")
            
            if len(summary.get('error_details', {})) > 5:
                remaining = len(summary['error_details']) - 5
                add_log(f"  ... and {remaining} more errors", "warning")
        
        add_log("", "info")
        add_log("✓ Validation complete!", "success")
        
        return jsonify({
            "status": "success",
            "total": summary['total'],
            "valid": summary['valid'],
            "invalid": summary['invalid']
        })
        
    except Exception as e:
        add_log(f"✗ Error: {str(e)}", "error")
        return jsonify({"error": str(e)}), 500

@app.route('/api/template', methods=['POST'])
def generate_template():
    """Generate blank metadata template"""
    try:
        data = request.json
        count = int(data.get('count', 1))
        
        if count < 1 or count > 100:
            return jsonify({"error": "Count must be between 1 and 100"}), 400
        
        add_log(f"\nGenerating {count} template(s)...", "info")
        
        output_files = []
        for i in range(count):
            template = generator.create_blank_template()
            
            if count == 1:
                filename = 'metadata_template.json'
            else:
                filename = f'metadata_template_{i+1}.json'
            
            filepath = os.path.join(app.config['OUTPUT_FOLDER'], filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump([template], f, indent=2, ensure_ascii=False)
            
            add_log(f"✓ Template created: {filename}", "success")
            output_files.append(filename)
        
        add_log(f"\n✓ Successfully created {count} template(s)", "success")
        
        return jsonify({
            "status": "success",
            "count": count,
            "files": output_files
        })
        
    except Exception as e:
        add_log(f"✗ Error: {str(e)}", "error")
        return jsonify({"error": str(e)}), 500

@app.route('/api/output-files')
def list_output_files():
    """List files in output folder"""
    try:
        files = []
        if os.path.exists(app.config['OUTPUT_FOLDER']):
            for file in os.listdir(app.config['OUTPUT_FOLDER']):
                filepath = os.path.join(app.config['OUTPUT_FOLDER'], file)
                if os.path.isfile(filepath):
                    size = os.path.getsize(filepath)
                    files.append({
                        "name": file,
                        "size": size,
                        "size_kb": round(size / 1024, 2)
                    })
        
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download/<filename>')
def download_file(filename):
    """Download file from output folder"""
    try:
        filepath = os.path.join(app.config['OUTPUT_FOLDER'], secure_filename(filename))
        
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404
        
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    add_log("Archipelago Metadata Generator & Enhancer Web Interface", "info")
    add_log("Starting server on http://localhost:5000", "success")
    print("\n🚀 Open http://localhost:5000 in your browser\n")
    app.run(debug=True, use_reloader=False)
