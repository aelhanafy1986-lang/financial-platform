import signal, threading, uvicorn
signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGBREAK, signal.SIG_IGN)
config = uvicorn.Config("app.main:app", port=8000, log_config=None)
server = uvicorn.Server(config)
server.install_signal_handlers = lambda: None
threading.Thread(target=server.run, daemon=True).start()
while True:
    try:
        threading.Event().wait()
    except BaseException:
        pass
