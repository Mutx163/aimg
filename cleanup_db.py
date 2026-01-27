import sqlite3
import os

DB_PATH = "aimg_metadata.db"

def fix_duplicates():
    if not os.path.exists(DB_PATH):
        print("Database not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all entries
    cursor.execute("SELECT id, file_path FROM images")
    rows = cursor.fetchall()
    
    print(f"Total rows: {len(rows)}")
    
    unique_paths = {} # norm_path -> list of (id, original_path)
    
    for rid, path in rows:
        norm = path.replace("\\", "/")
        if norm not in unique_paths:
            unique_paths[norm] = []
        unique_paths[norm].append((rid, path))
        
    duplicates_groups = {k: v for k, v in unique_paths.items() if len(v) > 1}
    normalized_groups = {k: v for k, v in unique_paths.items() if len(v) == 1 and v[0][1] != k}
    
    print(f"Found {len(duplicates_groups)} duplicate groups.")
    print(f"Found {len(normalized_groups)} entries needing normalization.")
    
    deleted_count = 0
    updated_count = 0
    
    # 1. Handle Duplicates: Keep the one with '/' if possible, or just the first one
    for norm, entries in duplicates_groups.items():
        # define priority: forward slash > back slash
        entries.sort(key=lambda x: 0 if '/' in x[1] and '\\' not in x[1] else 1)
        
        keep = entries[0]
        to_delete = entries[1:]
        
        # Delete duplicates
        for d in to_delete:
            cursor.execute("DELETE FROM images WHERE id = ?", (d[0],))
            deleted_count += 1
            
        # Ensure 'keep' is normalized
        if keep[1] != norm:
            cursor.execute("UPDATE images SET file_path = ? WHERE id = ?", (norm, keep[0]))
            updated_count += 1
            
    # 2. Handle Normalizations (non-duplicates that just have backslashes)
    for norm, entries in normalized_groups.items():
        rid = entries[0][0]
        cursor.execute("UPDATE images SET file_path = ? WHERE id = ?", (norm, rid))
        updated_count += 1

    conn.commit()
    conn.close()
    
    print(f"Cleanup complete. Deleted {deleted_count} duplicates. Normalized {updated_count} paths.")

if __name__ == "__main__":
    fix_duplicates()
