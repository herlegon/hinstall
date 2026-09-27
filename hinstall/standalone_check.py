import signal

def get_python_env() ->None:
    import sys, os
    print("Prefix:", sys.prefix)
    print("Base prefix:", sys.base_prefix)
    print("Exec prefix:", sys.exec_prefix)
    print("Python path:\n ", f"\n  ".join([v for v in sys.path]))
    print("User site:", getattr(sys, 'base_user_site', '(none)'))
    print("Environment:\n ", "\n  ".join([f"{k}: {os.environ[k]}" for k in sorted(os.environ.keys())]))


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    get_python_env()
