import re

def validate_stagecode(code: str):
    code = code.upper().replace('O', '0')
    
    if re.fullmatch(r'[A-Z0-9]{4}-[A-Z0-9]{4}', code):
        return code
    else:
        return False
    
