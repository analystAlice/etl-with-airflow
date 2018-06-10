INSERT INTO TABLE dv_raw.link_film_language
SELECT DISTINCT
    fl.film_language_bk as hkey_film_language,
    fl.dv__rec_source as record_source,
    fl.dv__load_dtm as load_dtm,
    fl.dv__bk as hkey_film,
    fl.language_bk as hkey_language
FROM
    staging_dvdrentals.film_{{ts_nodash}} fl
WHERE
    NOT EXISTS (
        SELECT 
                lfl.hkey_film_language
        FROM    dv_raw.link_film_language lfl
        WHERE 
                lfl.hkey_film = fl.dv__bk
        AND     lfl.hkey_language = fl.language_bk
    )
