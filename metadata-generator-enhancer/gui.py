"""
Windowed GUI interface for Archipelago Metadata Generator & Enhancer
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
from pathlib import Path
import json
import threading
from generator import MetadataGenerator
from validator import MetadataValidator


class MetadataGeneratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Archipelago Metadata Generator & Enhancer")
        self.root.geometry("900x750")
        self.root.resizable(True, True)
        
        # Initialize backend
        self.generator = MetadataGenerator()
        self.validator = MetadataValidator()
        self.current_records = None
        self.input_file = None
        self.output_dir = "./output"
        
        # Create GUI
        self.create_widgets()
    
    def create_widgets(self):
        """Create all GUI widgets"""
        # Style
        style = ttk.Style()
        style.theme_use('clam')
        
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(4, weight=1)
        
        # ===== Header =====
        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        
        title_label = ttk.Label(header_frame, text="Archipelago Metadata Generator & Enhancer", 
                               font=('Helvetica', 16, 'bold'))
        title_label.pack(side=tk.LEFT)
        
        # ===== File Selection Section =====
        file_frame = ttk.LabelFrame(main_frame, text="1. Upload File", padding="10")
        file_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        file_frame.columnconfigure(1, weight=1)
        
        ttk.Label(file_frame, text="Input File:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.file_path_label = ttk.Label(file_frame, text="No file selected", 
                                         foreground="gray")
        self.file_path_label.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        
        ttk.Button(file_frame, text="Browse CSV/JSON", 
                  command=self.select_input_file).grid(row=0, column=2, padx=5)
        
        # ===== Output Directory Section =====
        output_frame = ttk.LabelFrame(main_frame, text="2. Output Directory", padding="10")
        output_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        output_frame.columnconfigure(1, weight=1)
        
        ttk.Label(output_frame, text="Output Dir:").grid(row=0, column=0, sticky=tk.W, padx=5)
        self.output_label = ttk.Label(output_frame, text=self.output_dir)
        self.output_label.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        
        ttk.Button(output_frame, text="Choose Output Directory", 
                  command=self.select_output_dir).grid(row=0, column=2, padx=5)
        
        # ===== Options Section =====
        options_frame = ttk.LabelFrame(main_frame, text="3. Processing Options", padding="10")
        options_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Left column
        left_col = ttk.Frame(options_frame)
        left_col.grid(row=0, column=0, sticky=(tk.W, tk.N), padx=10)
        
        ttk.Label(left_col, text="Output Format:", font=('Helvetica', 10, 'bold')).pack(anchor=tk.W)
        self.format_var = tk.StringVar(value="both")
        ttk.Radiobutton(left_col, text="CSV", variable=self.format_var, 
                       value="csv").pack(anchor=tk.W)
        ttk.Radiobutton(left_col, text="JSON", variable=self.format_var, 
                       value="json").pack(anchor=tk.W)
        ttk.Radiobutton(left_col, text="Both CSV & JSON", variable=self.format_var, 
                       value="both").pack(anchor=tk.W)
        
        # Right column - Checkboxes
        right_col = ttk.Frame(options_frame)
        right_col.grid(row=0, column=1, sticky=(tk.W, tk.N), padx=10)
        
        ttk.Label(right_col, text="Processing Options:", font=('Helvetica', 10, 'bold')).pack(anchor=tk.W)
        self.enhance_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right_col, text="✓ Enhance records (fill defaults)", 
                       variable=self.enhance_var).pack(anchor=tk.W)
        
        self.normalize_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right_col, text="✓ Normalize names (people/organizations)", 
                       variable=self.normalize_var).pack(anchor=tk.W)
        
        self.validate_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right_col, text="✓ Validate records", 
                       variable=self.validate_var).pack(anchor=tk.W)
        
        # Right-right column - Template generation
        template_col = ttk.Frame(options_frame)
        template_col.grid(row=0, column=2, sticky=(tk.W, tk.N), padx=10)
        
        ttk.Label(template_col, text="Template Generation:", font=('Helvetica', 10, 'bold')).pack(anchor=tk.W)
        ttk.Label(template_col, text="Number of templates:").pack(anchor=tk.W)
        self.template_count = ttk.Spinbox(template_col, from_=1, to=100, width=10)
        self.template_count.set(1)
        self.template_count.pack(anchor=tk.W)
        
        # ===== Action Buttons =====
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        button_frame.columnconfigure(4, weight=1)  # Spacer
        
        ttk.Button(button_frame, text="📋 Generate Template", 
                  command=self.generate_template).grid(row=0, column=0, padx=5)
        
        ttk.Button(button_frame, text="⚙️  Process File", 
                  command=self.process_file).grid(row=0, column=1, padx=5)
        
        ttk.Button(button_frame, text="✓ Validate File", 
                  command=self.validate_file).grid(row=0, column=2, padx=5)
        
        ttk.Button(button_frame, text="🗂️  Open Output Folder", 
                  command=self.open_output_folder).grid(row=0, column=3, padx=5)
        
        # ===== Output/Log Section =====
        log_frame = ttk.LabelFrame(main_frame, text="4. Status & Results", padding="10")
        log_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, width=80, 
                                                  wrap=tk.WORD, state=tk.DISABLED)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure text tags for styling
        self.log_text.tag_config("success", foreground="green")
        self.log_text.tag_config("error", foreground="red")
        self.log_text.tag_config("info", foreground="blue")
        self.log_text.tag_config("warning", foreground="orange")
        
        # Initial message
        self.log("Archipelago Metadata Generator & Enhancer Ready!", "info")
        self.log("Select a CSV/JSON file to process or generate a new template.", "info")
    
    def log(self, message, tag="info"):
        """Add message to log"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n", tag)
        self.log_text.see(tk.END)  # Auto-scroll to bottom
        self.log_text.config(state=tk.DISABLED)
        self.root.update()
    
    def select_input_file(self):
        """Open file browser to select input file"""
        file_path = filedialog.askopenfilename(
            title="Select Metadata File",
            filetypes=[("CSV files", "*.csv"), ("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if file_path:
            self.input_file = file_path
            self.file_path_label.config(text=Path(file_path).name)
            self.log(f"✓ File selected: {file_path}", "success")
            
            # Try to load preview
            try:
                if file_path.endswith('.csv'):
                    self.current_records = self.generator.load_from_csv(file_path)
                elif file_path.endswith('.json'):
                    self.current_records = self.generator.load_from_json(file_path)
                
                self.log(f"✓ Loaded {len(self.current_records)} records", "success")
            except Exception as e:
                self.log(f"✗ Error loading file: {str(e)}", "error")
    
    def select_output_dir(self):
        """Open directory browser for output"""
        dir_path = filedialog.askdirectory(title="Select Output Directory")
        
        if dir_path:
            self.output_dir = dir_path
            self.output_label.config(text=dir_path)
            self.log(f"✓ Output directory set: {dir_path}", "success")
    
    def generate_template(self):
        """Generate blank metadata templates"""
        try:
            count = int(self.template_count.get())
            os.makedirs(self.output_dir, exist_ok=True)
            
            self.log(f"\nGenerating {count} template(s)...", "info")
            
            for i in range(count):
                template = self.generator.create_blank_template()
                
                if count == 1:
                    filename = os.path.join(self.output_dir, 'metadata_template.json')
                else:
                    filename = os.path.join(self.output_dir, f'metadata_template_{i+1}.json')
                
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump([template], f, indent=2, ensure_ascii=False)
                
                self.log(f"✓ Template created: {Path(filename).name}", "success")
            
            self.log(f"\n✓ Successfully created {count} template(s)", "success")
            
        except ValueError:
            self.log("✗ Invalid template count", "error")
        except Exception as e:
            self.log(f"✗ Error generating template: {str(e)}", "error")
    
    def process_file(self):
        """Process the input file with selected options"""
        if not self.input_file:
            messagebox.showwarning("No File", "Please select an input file first")
            return
        
        # Run in separate thread to prevent UI freezing
        thread = threading.Thread(target=self._process_file_thread)
        thread.daemon = True
        thread.start()
    
    def _process_file_thread(self):
        """Process file in background thread"""
        try:
            output_format = self.format_var.get()
            enhance = self.enhance_var.get()
            normalize_names = self.normalize_var.get()
            validate = self.validate_var.get()
            
            self.log(f"\n{'='*60}", "info")
            self.log(f"Processing file: {Path(self.input_file).name}", "info")
            self.log(f"{'='*60}", "info")
            
            os.makedirs(self.output_dir, exist_ok=True)
            
            # Load file
            self.log(f"Loading file...", "info")
            if self.input_file.endswith('.csv'):
                records = self.generator.load_from_csv(self.input_file)
            elif self.input_file.endswith('.json'):
                records = self.generator.load_from_json(self.input_file)
            else:
                self.log("✗ File must be .csv or .json", "error")
                return
            
            self.log(f"✓ Loaded {len(records)} records", "success")
            
            # Enhance if requested
            if enhance:
                self.log(f"Enhancing records...", "info")
                options = {
                    'fill_defaults': True,
                    'normalize_names': normalize_names,
                }
                self.generator.enhance_batch(options=options)
                self.log(f"✓ Records enhanced", "success")
            
            # Export
            basename = Path(self.input_file).stem
            
            if output_format in ['csv', 'both']:
                self.log(f"Exporting to CSV...", "info")
                csv_path = os.path.join(self.output_dir, f'{basename}_output.csv')
                result = self.generator.to_csv(csv_path, validate=validate)
                self.log(f"✓ CSV exported: {Path(csv_path).name}", "success")
                
                if result.get('validation_summary'):
                    summary = result['validation_summary']
                    self.log(f"  Valid: {summary['valid']}/{summary['total']} records", "info")
            
            if output_format in ['json', 'both']:
                self.log(f"Exporting to JSON...", "info")
                json_path = os.path.join(self.output_dir, f'{basename}_output.json')
                result = self.generator.to_json(json_path, validate=validate)
                self.log(f"✓ JSON exported: {Path(json_path).name}", "success")
            
            self.log(f"\n✓ Processing complete!", "success")
            self.log(f"Output files saved to: {self.output_dir}", "success")
            
        except Exception as e:
            self.log(f"✗ Error: {str(e)}", "error")
    
    def validate_file(self):
        """Validate the input file"""
        if not self.input_file:
            messagebox.showwarning("No File", "Please select an input file first")
            return
        
        # Run in separate thread
        thread = threading.Thread(target=self._validate_file_thread)
        thread.daemon = True
        thread.start()
    
    def _validate_file_thread(self):
        """Validate file in background thread"""
        try:
            self.log(f"\n{'='*60}", "info")
            self.log(f"Validating file: {Path(self.input_file).name}", "info")
            self.log(f"{'='*60}", "info")
            
            # Load records
            self.log(f"Loading file...", "info")
            if self.input_file.endswith('.csv'):
                records = self.generator.load_from_csv(self.input_file)
            elif self.input_file.endswith('.json'):
                records = self.generator.load_from_json(self.input_file)
            else:
                self.log("✗ File must be .csv or .json", "error")
                return
            
            self.log(f"✓ Loaded {len(records)} records\n", "success")
            
            # Validate
            self.log(f"Validating records against schema...", "info")
            summary = self.validator.validate_batch(records)
            
            # Display results
            self.log(f"\nValidation Results:", "info")
            self.log(f"  Total records: {summary['total']}", "info")
            self.log(f"  Valid records: {summary['valid']}", "success")
            self.log(f"  Invalid records: {summary['invalid']}", "warning" if summary['invalid'] > 0 else "success")
            
            if summary['invalid'] > 0:
                self.log(f"\nErrors found:", "warning")
                for idx, errors in list(summary.get('error_details', {}).items())[:5]:  # Show first 5
                    self.log(f"  Record {idx}: {errors}", "warning")
                
                if len(summary.get('error_details', {})) > 5:
                    self.log(f"  ... and {len(summary['error_details']) - 5} more errors", "warning")
            
            self.log(f"\n✓ Validation complete!", "success")
            
        except Exception as e:
            self.log(f"✗ Error: {str(e)}", "error")
    
    def open_output_folder(self):
        """Open the output folder in file explorer"""
        if os.path.exists(self.output_dir):
            import subprocess
            if os.name == 'nt':  # Windows
                subprocess.Popen(f'explorer "{os.path.abspath(self.output_dir)}"')
            elif os.name == 'posix':  # macOS/Linux
                subprocess.Popen(['open', self.output_dir])
            self.log(f"Opening output folder: {self.output_dir}", "info")
        else:
            messagebox.showwarning("Folder Not Found", "Output directory does not exist yet")


def main():
    """Launch the GUI application"""
    root = tk.Tk()
    app = MetadataGeneratorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
