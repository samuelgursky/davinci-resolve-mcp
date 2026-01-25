"""
bg_remover.py
=================
Author: Akascape
License: MIT License - Copyright (c) 2026 Akascape
Script Version: 0.2

Background Remover Script for DaVinci Resolve Fusion
This script uses the rembg library to remove backgrounds from images.
It is designed to be used within the DaVinci Resolve Fusion environment.
"""

import sys
import os
import time
import rembg
from PIL import Image

# Set UTF-8 encoding for better compatibility
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

class FuseBackgroundRemover:
    def __init__(self, model_name='u2netp'):
        """Initialize rembg with specified model"""

        self.log("="*50)
        self.log(f"Loading background removal model: {model_name}")

        try:
            self.session = rembg.new_session(model_name)
            self.log("[SUCCESS] Model loaded successfully!")

        except Exception as e:
            self.log(f"[ERROR] Error loading model {model_name}: {e}")
            self.log("[WARNING] Falling back to u2netp model")
        
            try:
                self.session = rembg.new_session('u2netp')
                self.log("[SUCCESS] Fallback model loaded successfully!")
            except Exception as fallback_error:
                self.log(f"[CRITICAL] Critical error: Could not load any model: {fallback_error}")
                raise fallback_error
    
    def log(self, message):
        """Print log message with timestamp and flush immediately."""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        try:
            print(f"[{timestamp}] {message}")
            sys.stdout.flush()  
        except UnicodeEncodeError:
            # Fallback for encoding issues
            print(f"[{timestamp}] {message.encode('ascii', 'ignore').decode('ascii')}")
            sys.stdout.flush()
    
    def process_image(self, input_path, output_path):
        """Remove background from image file."""
        try:
            # Log processing start
            self.log("-"*50)
            self.log(f"[INPUT] Input path: {input_path}")
            self.log(f"[OUTPUT] Output path: {output_path}")
            
            # Check if input file exists
            if not os.path.exists(input_path):
                self.log(f"[ERROR] Input file does not exist: {input_path}")
                return False
            
            # Load image
            self.log("[STEP 1/4] Loading image...")
            pil_image = Image.open(input_path)
            self.log(f"Image loaded: {pil_image.size[0]}x{pil_image.size[1]} pixels, mode: {pil_image.mode}")
            
            # Ensure RGB mode for processing
            if pil_image.mode != 'RGB':
                self.log(f"[STEP 2/4] Converting from {pil_image.mode} to RGB...")
                pil_image = pil_image.convert('RGB')
            else:
                self.log("[STEP 2/4] Image already in RGB mode")
            
            # Remove background
            self.log("[STEP 3/4] Running background removal AI model...")
            start_time = time.time()
            
            result = rembg.remove(pil_image, session=self.session)
            
            processing_time = time.time() - start_time
            self.log(f"[SUCCESS] Background removal completed in {processing_time:.2f} seconds")
            self.log(f"[INFO] Output image: {result.size[0]}x{result.size[1]} pixels, mode: {result.mode}")
            # Save with transparency (PNG)
            result.save(output_path, "PNG")
            self.log(f"[SUCCESS] Saved with transparency: {os.path.basename(output_path)}")
            # Verify output file was created
            if not os.path.exists(output_path):
                self.log("[ERROR] Output file generation failed!")
                return False
            self.log("-"*50)
            return True
            
        except Exception as e:
            self.log(f"[ERROR] Error processing image: {e}")
            self.log(f"[ERROR] Exception type: {type(e).__name__}")
            return False

def main():

    def log_main(message):
        """Log messages with timestamp for the main script."""
        timestamp = time.strftime("%H:%M:%S", time.localtime())
        try:
            print(f"[{timestamp}] MAIN: {message}")
            sys.stdout.flush()
        except UnicodeEncodeError:
            print(f"[{timestamp}] MAIN: {message.encode('ascii', 'ignore').decode('ascii')}")
            sys.stdout.flush()
    
    log_main("[START] REMBG Script Started")

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    input_path = sys.argv[1]
    output_path = sys.argv[2]
    model_name = sys.argv[3]
    if not os.path.exists(input_path):
        log_main(f"[ERROR] Input file does not exist: {input_path}")
        sys.exit(1)
    
    # Initialize background remover
    try:
        log_main("[INIT] Initializing REMBG...")
        bg_remover = FuseBackgroundRemover(model_name)
        
        # Process the image
        # Process the image
        success = bg_remover.process_image(input_path, output_path)
        if success:
            log_main("[COMPLETE] Background removal completed successfully!")
            sys.exit(0)
        else:
            log_main("[FAILED] Background removal failed!")
            sys.exit(1)
            
    except Exception as e:
        log_main(f"[FATAL] Fatal error: {e}")
        log_main(f"[FATAL] Exception type: {type(e).__name__}")
        log_main("[CHECK] Check your Python environment and dependencies")
        sys.exit(1)

if __name__ == "__main__":
    main()