
def resolve_jsonl():
    path = r'data/research_gap_dataset.jsonl'
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # We want to remove lines 54, 57, 58, 59, 60 (indices 53, 56, 57, 58, 59)
    # And keep 55, 56 (indices 54, 55)
    
    # Just to be safe, let's verify the markers
    if '<<<<<<<' in lines[53] and '=======' in lines[56] and '>>>>>>>' in lines[59]:
        new_lines = lines[:53] + lines[54:56] + lines[60:]
        with open(path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print("Successfully resolved conflicts.")
    else:
        print("Markers not found at expected lines. Checking file content...")
        for i, line in enumerate(lines[50:65]):
            print(f"{i+51}: {line[:50]}...")

if __name__ == '__main__':
    resolve_jsonl()
