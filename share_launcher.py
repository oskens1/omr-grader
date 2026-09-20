"""Portable GUI entry and repeatable batch acceptance entry."""
from pathlib import Path
import sys, os, json, argparse, traceback

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--batch',type=Path)
    ap.add_argument('--config',type=Path)
    ap.add_argument('--output',type=Path)
    ap.add_argument('--mode',default='PRINTED_0914')
    ap.add_argument('--gui-probe',type=Path)
    a=ap.parse_args()
    home=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    # No implicit private user settings; all portable files live beside the EXE.
    os.chdir(home)
    if getattr(sys,'frozen',False):
        qt_dir=Path(sys._MEIPASS)/'PyQt6/Qt6/bin'
        dll_handle=os.add_dll_directory(str(qt_dir))
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    from main_qt import MainWindow, GradingThread
    from config_manager import ConfigManager
    from omr_upgrade import OMRProcessor
    app=QApplication(sys.argv);app.setStyle('Fusion')
    if a.batch:
        if not a.config or not a.output: ap.error('--batch requires --config and --output')
        a.output.mkdir(parents=True,exist_ok=False)
        mgr=ConfigManager(str(a.config));ok,msg=mgr.load_config()
        if not ok: raise ValueError(msg)
        core=OMRProcessor(str(Path(getattr(sys,'_MEIPASS',home))/'assets'))
        worker=GradingThread(str(a.batch),str(a.output),core,mgr,a.mode)
        messages=[];done=[]
        worker.log_signal.connect(messages.append)
        worker.finished_signal.connect(lambda ok,msg:done.append({'ok':ok,'message':msg}))
        worker.run()
        (a.output/'run_log.json').write_text(json.dumps({'done':done,'messages':messages},ensure_ascii=False,indent=2),encoding='utf-8')
        return 0 if done and done[-1]['ok'] else 1
    window=MainWindow();window.show()
    if a.gui_probe:
        def probe():
            a.gui_probe.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(a.gui_probe/'window.png'))
            (a.gui_probe/'gui.json').write_text(json.dumps({'title':window.windowTitle(),'visible':window.isVisible(),'modes':[window.card_combo.itemData(i) for i in range(window.card_combo.count())]},ensure_ascii=False),encoding='utf-8')
            app.quit()
        QTimer.singleShot(1200,probe)
    return app.exec()

if __name__=='__main__':
    try: sys.exit(main())
    except Exception:
        base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
        (base/'crash_log.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
