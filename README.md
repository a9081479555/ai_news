# AI Infrastructure Corporate Banking Analysis

本套件為可部署的 v13 研究平台，涵蓋 6 大系統、18 個子產業、Evidence Grade、子產業與公司象限、RM金融產品提案，以及「每日新聞＋Weekly Intelligence」審核發布管線。

## 使用方式

- 本機網站：直接開啟 `index.html`；新聞JSON若因 `file://`限制無法載入，可在專案目錄執行 `python -m http.server 8000`，再開啟 `http://localhost:8000/`。
- GitHub Pages：Pages Source選擇 GitHub Actions，`pages.yml`只發布公開網站、`assets/`及`data/public/`。
- Netlify／Vercel：將本資料夾或 ZIP 上傳為靜態網站，不需要 build command。

## 新聞審核與發布

1. `python scripts/news_pipeline.py collect`：抓取RSS／新聞搜尋、去重、分類，寫入`data/review/news_queue.json`。
2. 以`review-dashboard.html`檢視候選事件與新台廠候選池。
3. 將核准ID逐行寫入`config/approved_news_ids.txt`。
4. `python scripts/news_pipeline.py publish`：只把明確核准事件寫入`data/public/news.json`。
5. `python scripts/news_pipeline.py weekly`：從已核准事件產生`data/public/weekly.json`。

安全要求：`data/review/`與`review-dashboard.html`不會被Pages工作流程發布，但若GitHub repository本身是公開的，原始檔仍可被看見。若待審核內容必須私有，來源repository必須設為private且方案需支援公開Pages，或拆成「私人審核repo＋公開網站repo」。

## 研究限制

本網站僅供產業研究、企業金融客戶篩選與 RM 訪談準備，不構成授信核准或投資建議。A／B／C 是證據強度，不是信用評等或市場排名。公開資料不足之處均應依網站所列 Evidence Gap 補件；N/A 不納入有效分數平均。

## 檔案

- `index.html`：核心研究網站
- `daily-news.html`：已核准每日新聞
- `weekly-intelligence.html`：已核准週報
- `review-dashboard.html`：私人待審核頁面，不納入Pages部署
- `scripts/news_pipeline.py`：收集、核准發布與週報管線
- `.github/workflows/`：每日排程、核准發布與Pages部署
- `README.md`：部署與使用說明
- `.nojekyll`：GitHub Pages 靜態部署設定

## 財務評分資料管線

`scripts/financial_scoring_pipeline.py`可在具備Python 3與外網連線的環境抓取MOPS公開財報、計算GPM、CapEx／Revenue及營運資金需求比率，並結合`config/growth_inputs.csv`重算18個子產業的新象限分數。詳細操作請見`scripts/README.md`。網站分數必須等資料抓取、Evidence Gap與原始財報覆核完成後才能替換。
