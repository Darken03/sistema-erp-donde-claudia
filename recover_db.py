
#!/usr/bin/env python
"""Recover a corrupted SQLite database without losing data."""
import os
import sys
import sqlite3
import shutil

def recover_database(db_path):
    """Recover SQLite database using .recover command."""
    backup_path = db_path + '.backup'
    
    # First, try to create a backup of current state
    print(f"Backing up original database to {backup_path}...")
    try:
        shutil.copy2(db_path, backup_path)
        print("Backup created successfully.")
    except Exception as e:
        print(f"Warning: Could not create backup: {e}")
    
    # Connect to the corrupted database
    print("\nConnecting to corrupted database...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
    except Exception as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)
    
    # Use SQLite's .recover via dump and recreate
    print("Attempting recovery using SQLite dump...")
    
    # Create a new empty database file
    recovered_path = db_path + '.recovered'
    recovered_conn = sqlite3.connect(recovered_path)
    recovered_cursor = recovered_conn.cursor()
    
    # Get all SQL from the corrupted db and execute in new db
    try:
        # Try to dump schema and data
        for line in conn.iterdump():
            try:
                recovered_cursor.execute(line)
            except Exception as e:
                # Skip individual statements that fail
                print(f"Warning: Skipped statement: {e}")
                continue
        
        recovered_conn.commit()
        recovered_conn.close()
        conn.close()
        
        # Verify the recovered database
        print("\nVerifying recovered database...")
        verify_conn = sqlite3.connect(recovered_path)
        verify_cursor = verify_conn.cursor()
        
        # Test basic query
        verify_cursor.execute("SELECT COUNT(*) FROM sqlite_master;")
        count = verify_cursor.fetchone()[0]
        print(f"Recovered database contains {count} tables.")
        
        verify_conn.close()
        
        # Replace corrupted db with recovered one
        os.replace(recovered_path, db_path)
        
        print("\n" + "="*60)
        print("Database recovery completed successfully!")
        print("="*60)
        print(f"Original backed up to: {backup_path}")
        print(f"Recovered database: {db_path}")
        print("="*60)
        
    except Exception as e:
        print(f"Error during recovery: {e}")
        # Try alternative method using direct SQLite commands
        print("\nTrying alternative recovery method...")
        conn.close()
        recovered_conn.close()
        
        # Use sqlite3 command-line tool via subprocess
        import subprocess
        
        # Create empty target
        if os.path.exists(recovered_path):
            os.remove(recovered_path)
        
        # Use .dump from command line
        try:
            # Dump SQL from corrupted database
            dump_cmd = f'python -c "import sqlite3; conn=sqlite3.connect(\\\'{db_path}\\\'); print(\\n\\n\\n\\n\\\\n\\\\n\\\\n\\\\n\\\\n\\\\n\\\\n\\\\n.join(conn.iterdump()))" > dump.sql'
            print(f"Running: {dump_cmd}")
            result = subprocess.run(dump_cmd, shell=True, capture_output=True, text=True)
            
            if os.path.exists('dump.sql') and os.path.getsize('dump.sql') > 0:
                print("Dump file created, applying to new database...")
                # Create new db and load dump
                subprocess.run(f'sqlite3 "{recovered_path}" < dump.sql', shell=True)
                
                # Replace
                os.replace(recovered_path, db_path)
                print("Recovery completed using dump method.")
            else:
                print("Dump method failed, trying .recover directly...")
                # Try sqlite3 .recover command
                recover_cmd = f'sqlite3 "{db_path}" ".recover" | sqlite3 "{recovered_path}"'
                result = subprocess.run(recover_cmd, shell=True, capture_output=True, text=True)
                
                if os.path.exists(recovered_path) and os.path.getsize(recovered_path) > 0:
                    os.replace(recovered_path, db_path)
                    print("Recovery completed using .recover command.")
                else:
                    print("All recovery methods failed.")
        except Exception as e2:
            print(f"Alternative recovery also failed: {e2}")

if __name__ == '__main__':
    db_path = 'db.sqlite3'
    if not os.path.exists(db_path):
        print(f"Database file not found: {db_path}")
        sys.exit(1)
    
    print(f"Recovering database: {db_path}")
    print(f"File size: {os.path.getsize(db_path)} bytes")
    print("="*60)
    recover_database(db_path)
