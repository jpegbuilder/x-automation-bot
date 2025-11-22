import sys


def validate_settings():
    """Check all required environment variables from settings.py"""
    from config import settings as settings_module

    errors = []

    required_vars = {k: v for k, v in vars(settings_module).items() if k.isupper()}

    for var_name, var_value in required_vars.items():
        if not var_value or (isinstance(var_value, str) and var_value.strip() == ''):
            errors.append(f"[X] {var_name} - missing or empty")

    if errors:
        print("\n[!] ERRORS CONFIG:\n")
        for error in errors:
            print(f"  {error}")
        print(f"\n[X] The server cannot start. Please set all required environment variables.\n")
        sys.exit(1)

    print("\n[OK] All settings are fine!\n")
    return True


if __name__ == "__main__":
    validate_settings()