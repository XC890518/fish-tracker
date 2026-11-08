# 魚隻位置追蹤與 novel tank 上下層分析

[English](#english) | [繁體中文](#魚隻位置追蹤與-novel-tank-上下層分析)

這是一個單魚、固定鏡頭、魚比背景暗的影片追蹤工具。可針對每支影片自行調整四邊形水槽範圍，並設定水平的上下層分界；以背景差分偵測魚的中心位置，輸出逐筆位置與摘要 CSV。預設值依資料夾中的範例影片設計，不保證適合所有影片。

本儲存庫不包含原始實驗影片或分析結果。Windows 使用者可在 GitHub Releases 下載可執行檔及附帶的授權與說明檔；程式首次啟動可能需要時間解壓縮。可執行檔尚未數位簽章。介面英文翻譯目前不完整。

## 開始使用

1. 在 Windows 雙擊 `啟動魚隻追蹤.bat`。本機需要 Python、NumPy、SciPy、Pillow，以及可從 PATH 執行的 `ffmpeg` 和 `ffprobe`。如果已安裝，本機無須再下載套件。
2. 按「選擇影片」，開啟要分析的影片。第一張畫面會顯示在視窗中。
3. 以滑鼠拖曳初始矩形，再拖動四個綠色角點以貼合水槽內部；盡量避開水槽邊緣、日期時間與其他物體。只有綠色四邊形內參與偵測。四個角須維持凸四邊形，避免交叉或凹陷。位置是每支影片各自設定。
4. 黃色水平線預設在框選範圍的中央。在框內點擊新的高度即可更改分界；線以上為 `top`，線上及以下為 `bottom`。
5. 按「開始分析並儲存」，選擇位置與 CSV 檔名。程式先從影片各時間點建立背景，然後追蹤；完成後會同時建立位置 CSV、名稱加上 `_summary` 的摘要 CSV，以及名稱加上 `_tracked` 的 MP4 追蹤影片。分析期間紅圈顯示正在偵測的位置，按「取消分析」可取消。

追蹤影片以綠框顯示分析範圍、黃線顯示上下層分界、紅色十字顯示偵測位置；畫面左上角顯示原影片時間、所在層與原影片像素座標。`MISSING` 表示該取樣影格沒有偵測結果。影片只包含 CSV 中有分析的取樣影格，以相應影格率播放、維持原本的時間速度，因此預設每 5 張取 1 張時畫面較不流暢；若要逐影格檢查，請將取樣間隔設為 1。輸出影片最寬 1280 像素、不含原音訊，CSV 座標仍以原影片像素為準。輸出影片編碼使用 FFmpeg 的 libx264。

分析也會輸出同名的 `_heatmap.png` 熱區圖及 `_trajectory.png` 軌跡圖。熱區圖將成功偵測的取樣座標累積並平滑：藍色表示較少、紅色表示較多；強度依每張圖的最大值各自正規化，不宜直接以顏色比較不同影片的絕對停留時間。軌跡圖以紅線連接連續的有效座標，遇到 `missing` 會斷線，不跨越缺失影格。兩圖以原影片第一張畫面為背景，綠框和黃線分別表示分析範圍及上下層分界。手動修正後另存時，也會以修正後的資料重新輸出兩張圖。

新電腦若缺少 Python 套件，可在命令提示字元執行 `python -m pip install numpy scipy pillow`；另需安裝 FFmpeg，並將其執行檔所在資料夾加入系統 PATH（`ffmpeg`、`ffprobe` 都必須能執行）。

### 從原始碼建立 Windows 執行檔

在 Windows 64 位元環境安裝 Python 3.12、`requirements.txt` 與 PyInstaller；設定環境變數 `FFMPEG_DIR` 為含有 `ffmpeg.exe` 和 `ffprobe.exe` 的目錄，然後執行 `python -m PyInstaller --noconfirm --clean FishTracker.spec`。成品位於 `dist/FishTracker.exe`。發佈時須依所使用的 FFmpeg 與其第三方元件授權，提供適當的授權、來源及建置資訊。此專案的範例執行檔使用 FFmpeg 7.1.1 full build（GPL v3）。

## 手動修正

按主畫面的「手動修正結果」，選擇先前輸出的追蹤位置 CSV；同資料夾必須保留其 `_summary.csv`，而原影片也須保留在摘要中記錄的位置。舊版矩形結果亦可開啟。使用「上一筆／下一筆」或左右方向鍵切換取樣影格，也可輸入秒數跳到最近的取樣影格。直接在綠色範圍內點魚的位置，即修正該筆；若這張畫面沒有魚，可按「標記未偵測」。一次只修正目前取樣影格，沒有自動修正其前後影格。精確讀取較後面的原始影格可能需要等待。

完成後按「另存修正結果」，指定新 CSV 名稱。程式會從相同的修正資料重新產生位置 CSV、摘要 CSV 與追蹤影片；預設不覆寫原始結果。修正後位置 CSV 的 `correction` 欄位以 `manual` 標示手動變更的筆數，摘要中的 `manual_corrections` 記錄數量。可再開啟修正後的 CSV 繼續編輯。

## 可調整參數

- **輸出追蹤影片**：預設勾選；若只需要 CSV、摘要、熱區圖和軌跡圖，可以取消勾選以加快分析。此時不會產生 MP4，無法用追蹤影片直接檢查誤判；可在之後開啟「手動修正結果」並另存，重新輸出含影片的結果。快速模式請使用新的檔名，避免與既有影片混淆。

- **每幾影格取樣**：預設每 5 張取 1 張；設成 1 可逐影格分析，但耗時和檔案較大。範例影片約 30.3 fps，預設約每秒 6 次。
- **偵測閾值**：預設 15，範圍 1–255。較低較敏感，但容易誤判；較高可減少雜訊，但可能漏掉魚。
- **最小／最大面積**：預設 50／5000，限制深色候選物件的面積。面積單位是分析用縮小影像的像素，並非原始影像像素；摘要檔記錄分析影像尺寸。漏偵測小魚可降低最小面積，雜點誤判可提高它。

## 輸出欄位與解讀

位置 CSV 每列對應一個取樣影格：

- `frame`：從 0 開始的原始影格編號；`time_s`：由影格編號除以影片平均 fps 得到的秒數。
- `x_px`, `y_px`：魚體偵測區域的中心，單位為原始影片像素；原點在原影片左上角，x 向右增加、y 向下增加。
- `x_relative`, `y_relative`：相對於四邊形外接矩形的座標，外接矩形左上角為 0、右下角為 1；這不是透視校正後的水槽座標。
- `zone`：`top` 或 `bottom`；`status`：`detected` 或 `missing`。未找到符合條件的物件時，座標與區域留空，不插值。

摘要 CSV 包含範圍、分界、設定、偵測率、上下層觀察秒數、觀察移動距離（原始影片像素）及觀察到的跨層次數。上下層時間只累計兩端都成功偵測的相鄰取樣區間，並依區間起點所在層計算；缺漏區間和最後一筆之後的時間不計入。距離與跨層次數也不跨越缺漏區間。取樣間隔愈長，這些值可能低估，且跨越分界的時間較不精確。距離尚未校正為公分。

背景由全片 21 個時間點的中位數估計；如果魚長時間不動、照明變化、魚接近背景顏色、反光或其他移動物進入水槽，可能漏判或誤判。`detected` 只表示找到符合條件的物件，並不保證就是魚；偵測率也不能代表正確率。請觀看追蹤影片並參考位置 CSV，特別檢查開始、魚靠近邊緣及跨層的時候；不理想時調整框選範圍或參數重新分析。預設方法適用一隻魚，不適用多魚個體識別。

---

# English

## Fish tracking and novel tank analysis

Fish Tracker is a video-based tool for tracking a **single fish** in a fixed-camera recording where the fish appears darker than the background. It uses background subtraction to estimate the fish's position, classify it into upper and lower zones, and export tracking data and visualizations. Parameters were chosen for a sample recording and may need adjustment for other videos.

The repository does not include experimental videos or analysis results. The GUI's English translation is currently incomplete.

## Download and run

Download the Windows 64-bit executable and accompanying license and instructions from [Releases](https://github.com/XC890518/fish-tracker/releases/latest). Python and FFmpeg do not need to be installed separately for the executable. The first launch may take time while bundled files are extracted. The executable is not digitally signed.

To run from source on Windows, install Python, NumPy, SciPy and Pillow, and install FFmpeg with both `ffmpeg` and `ffprobe` available on `PATH`. Install the Python dependencies with `python -m pip install -r requirements.txt`, then run `python fish_tracker.py` or double-click `啟動魚隻追蹤.bat`.

## Workflow

1. Open a video and drag a rectangle over the area where the fish can swim.
2. Drag the four green corner handles to fit the tank. The resulting quadrilateral must remain convex; only its interior is used for detection. Avoid tank edges, timestamps and other objects.
3. Click to set the horizontal yellow divider. Points above it are classified as `top`; points on or below it are `bottom`.
4. Select **Analyze and save**, then choose a CSV file name. The program estimates a background from the video and tracks the fish.
5. Review the results against the video, especially near tank edges, zone crossings and the start of the recording.

The tracking CSV, summary CSV, heatmap and trajectory image are always generated. The annotated MP4 is generated when **Export video** is selected. Uncheck it for faster analysis if the video is not needed; use a new output name to avoid confusing the results with an older MP4. A corrected export can generate the video later.

## Manual correction

Select **Manual correction** and open a tracking CSV. Keep its matching `_summary.csv` in the same folder and the original video at the location recorded in the summary. Use Previous/Next or the left and right arrow keys to inspect sampled frames; you can also jump to the nearest sample by time. Click the fish's correct location inside the green region or mark the sample as missing. Each edit affects only the selected sampled frame; neighboring frames are not corrected automatically. Reading frames near the end of a video may take time.

Save corrected results to create a new CSV, summary, video, heatmap and trajectory from the same corrected data. The `correction` field marks manually edited rows as `manual`; `manual_corrections` in the summary counts them. The corrected CSV can be reopened for further edits.

## Settings

- **Sample every N frames:** Default 5. Use 1 for every frame, at the cost of longer processing and larger output files.
- **Threshold:** Default 15, on a scale of 1–255. Lower values are more sensitive but may detect noise; higher values can miss the fish.
- **Minimum / maximum area:** Defaults 50 / 5000. These filter candidate dark objects by area in the resized analysis image, not the original video. The analysis dimensions are recorded in the summary.

## Outputs and interpretation

The position CSV contains one row per sampled frame:

- `frame`: zero-based original frame number; `time_s`: frame number divided by the video's average frame rate.
- `x_px`, `y_px`: detected object's center in original-video pixels. The origin is the top-left corner; x increases to the right and y increases downward.
- `x_relative`, `y_relative`: position relative to the quadrilateral's bounding rectangle, from 0 at its top or left edge to 1 at its bottom or right edge. These are not perspective-corrected tank coordinates.
- `zone`: `top` or `bottom`; `status`: `detected` or `missing`. Missing samples have blank positions and zones; they are not interpolated.

The summary records the selected region, divider and parameters, detection rate, observed time in each zone, observed distance in original-video pixels and observed zone transitions. Zone time is accumulated only between adjacent samples that are both detected, using the zone at the start of the interval. Time after the final sample and intervals with missing endpoints are excluded. Distance and transitions are also not calculated across missing samples. Longer sampling intervals may underestimate these measures and reduce the precision of zone-crossing times. Distance is not calibrated in centimeters.

The annotated video shows the region in green, divider in yellow and detected position in red. `MISSING` means no object was detected in that sample. It contains only sampled frames at the corresponding frame rate, preserving approximate real-time playback; the default sampling can therefore look less smooth. The video is at most 1280 pixels wide and has no audio; CSV coordinates remain in original-video pixels.

The heatmap accumulates and smooths detected sample positions (blue for lower and red for higher density). Each heatmap is normalized to its own maximum, so colors should not be used to compare absolute time across recordings. The trajectory connects consecutive detected positions and breaks the line at missing samples. Both images use the first video frame as a background.

## Limitations

The background is the median of 21 frames sampled across the video. A stationary fish, changing lighting, low contrast, reflections or other moving objects can cause missed or false detections. `detected` means a candidate object was found, not that it was necessarily the fish; detection rate is not an accuracy measure. Inspect the annotated video and CSV, and adjust the region or parameters when needed. The tool is not designed to identify multiple individual fish.

## Build the Windows executable

On 64-bit Windows, install Python 3.12, the packages in `requirements.txt`, and PyInstaller. Set `FFMPEG_DIR` to the directory containing `ffmpeg.exe` and `ffprobe.exe`, then run:

```powershell
python -m PyInstaller --noconfirm --clean FishTracker.spec
```

The executable is written to `dist/FishTracker.exe`. When distributing it, provide the appropriate license, source and build information for the FFmpeg build and its third-party components. The example executable uses FFmpeg 7.1.1 full build (GPL v3).
