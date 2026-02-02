#!/usr/bin/env python3
"""
Watch for changes in templates/ and auto-rebuild pages.
Useful for local development.
"""

import time
import subprocess
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class TemplateChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self.last_build = 0
        
    def on_modified(self, event):
        if event.is_directory:
            return
        
        # Only rebuild for template files
        if not (event.src_path.endswith('.html') or event.src_path.endswith('.content.html')):
            return
            
        # Debounce - don't rebuild more than once per second
        now = time.time()
        if now - self.last_build < 1:
            return
        
        self.last_build = now
        print(f"\n📝 Changed: {Path(event.src_path).name}")
        print("🔨 Rebuilding...")
        
        try:
            result = subprocess.run(['python3', 'build.py'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=10)
            if result.returncode == 0:
                print("✓ Build complete!\n")
            else:
                print(f"❌ Build failed:\n{result.stderr}")
        except Exception as e:
            print(f"❌ Error: {e}")

def main():
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("Error: watchdog not installed")
        print("Install with: pip3 install watchdog")
        return
    
    template_dir = Path('templates')
    
    if not template_dir.exists():
        print(f"Error: {template_dir} directory not found")
        return
    
    print("👀 Watching templates/ for changes...")
    print("Output: docs/")
    print("Press Ctrl+C to stop\n")
    
    event_handler = TemplateChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, str(template_dir), recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Stopping watch...")
        observer.stop()
    
    observer.join()

if __name__ == '__main__':
    main()
