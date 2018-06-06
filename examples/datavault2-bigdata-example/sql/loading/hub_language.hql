INSERT INTO TABLE dv_raw.hub_language
SELECT DISTINCT
      a.dv__bk as hkey_language
    , a.dv__rec_source as rec_source
    , a.dv__load_dtm as load_dtm
    , a.name
FROM
    staging_dvdrentals.language_{{ts_nodash}} a
WHERE
    (a.dv__status = 'NEW' OR a.dv__status = 'UPDATED')
AND
    NOT EXISTS (
        SELECT 
                hub.hkey_language
        FROM 
                dv_raw.hub_language hub
        WHERE
                hub.name = a.name
    )
