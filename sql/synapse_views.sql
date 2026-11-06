-- Jalankan di Synapse Studio > Develop > SQL script > Connect to: Built-in (serverless).
-- Ganti <LAKE> dengan nama storage account lake (st...lake...).
CREATE DATABASE tcba7;
GO
USE tcba7;
GO
CREATE VIEW dbo.v_features AS
SELECT * FROM OPENROWSET(BULK 'https://<LAKE>.dfs.core.windows.net/gold/features/features_quarterly.parquet',
                         FORMAT = 'PARQUET') AS r;
GO
CREATE VIEW dbo.v_predictions AS
SELECT * FROM OPENROWSET(BULK 'https://<LAKE>.dfs.core.windows.net/gold/ml/latest/predictions.parquet',
                         FORMAT = 'PARQUET') AS r;
GO
CREATE VIEW dbo.v_retrain_log AS
SELECT * FROM OPENROWSET(BULK 'https://<LAKE>.dfs.core.windows.net/gold/ml/retrain_log.parquet',
                         FORMAT = 'PARQUET') AS r;
GO
-- Contoh analitik: rata-rata sentimen vs arah ROE kuartal berikutnya
SELECT ticker, label, COUNT(*) AS n, AVG(sent_mean) AS avg_sentiment, AVG(ret_q) AS avg_return
FROM dbo.v_features WHERE label IS NOT NULL GROUP BY ticker, label ORDER BY ticker, label;
