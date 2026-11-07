import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    os.environ['PATH'] = str(Path(sys._MEIPASS) / 'ffmpeg') + os.pathsep + os.environ.get('PATH', '')

import fish_tracker

if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--smoke-test':
        from threading import Event
        import fish_review
        output = Path(sys.argv[3])
        result = fish_tracker.track(sys.argv[2], (180, 140, 1550, 830), 550, 5, 15, 50, 5000,
                                    output, lambda *args: None, Event(), max_frames=30)
        rows, settings, source, roi, polygon = fish_review.load_data(output)
        rows[0].update(x_px='400', y_px='300', x_relative='0.14194', y_relative='0.19277',
                       zone='top', status='detected', correction='manual')
        fish_review.save_corrected(output.with_name(output.stem + '_corrected.csv'), rows, settings,
                                   source, roi, polygon, lambda *args: None)
    else:
        fish_tracker.main()
