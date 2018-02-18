Data Vault 2
============

.. important::

    This example is work in progress...

This is probably the final and most elaborate example of how to use ETL with Apache Airflow.
As part of this exercise, let's build a data warehouse on Google BigQuery with a DataVault
built on top of Hive. (Consequently, this example requires a bit more memory and may not fit in a simple machine).
We're going to start a postgres instance that contains the airflow database and another 
database for the adventureworks database created by Microsoft. We'll use a Postgres port
of that.

The data will be loaded into a Hive instance from there and in Hive we'll set up the Data Vault
structures. Optionally, if you have a Google account you'd like to try out, you can set up a 
connection later on and load some flat tables into BigQuery out of the Data Vault as a final 
part of this exercise; that will basically become our information mart. 
Alternatively, let's look into building a Kimball model out of it.

Note that similar to the Hive example, I'm using a special build of the puckel docker airflow
container that contains the jar files for Hadoop, HDFS and Hive.

.. important::

    The default login for "Hue", the interface for the Cloudera quickstart container running Hive 
    is cloudera/cloudera.

We are also going to attempt to output some CSV files that are to be imported into databook.
What is databook?  It's an opensource project I'm running that attempts to replicate what Airbnb
made in their "DataPortal" description. You can read more about databook here:

`Databook <https://github.com/gtoonstra/databook>`_

Finally, let's re-test all the work we did against the ETL principles that I wrote about to see
if all principles are covered and identify what are open topics to cover for a full-circle solution.

About Datavault
---------------

In the :doc:`/datavault` example, we explained some of the benefits of using a datavaulting methodology
to build your data warehouse and other rationales. Go there for some of the core reasons why data vaulting
is such a nice methodology to use in the middle.

This example uses some other techniques and attempts to implement all the best practices associated with
data vaulting. The "2.0" refers to some improvements that have been made since the first version of the 
methodology came out. One of the primary changes is the use of hashes as a means to improve the parallel
forward flow of the data going into the final information marts and intermediate processing. I'll point out
where hashing is somewhat problematic.

Overall flow
------------

This is the general flow to get data from the OLTP system into (eventually) the information mart. 
Here you can see how the Data Vault essentially fulfills the role of the Enterprise Data Warehouse
as described by Ralph Inmon, years ago.

.. image:: img/dataflow.jpeg

Staging flow
------------

Staging is the process where you pick up data from a source system and load it into a 'staging' area
keeping as much as possible of the source data intact. "Hard" business rules may be applied,
for example changing the data type of an item from a string into a datetime, but you should avoid 
splitting, combining or otherwise modifying the incoming data elements and leave that to a following step.
The latter are called "soft" business rules and are usually transformations related to interpretation
of the data. In short: operations where you may lose information should be avoided.

The staging area is temporary and I'm assuming delta loads are possible from the source system because of
a cdc solution being in place. If delta loads cannot be implemented due to a lack of proper CDC, then 
a persistent staging area (PSA) should be set up, so you can generate delta loads from there and
identify the deletes. Both the latter and the CDC solution should be capable to detect deletes.

Our staging approach for all tables in the adventureworks dataset will be:

1. Clear out staging table (truncate or drop). In the case of Hive, we use a temporary table with a date and time tag at the end. This means that each particular staging table can only reference data from the current data load.
2. (optional) disable indexes. As we use Hive, this is not relevant, there are no indexes set.
3. Bulk Read source data in order. In this example we bulk read "everything" from the entire source system because there are no useful change date/times in the source data. In a real application, you'd divide the data through the "updated_dtm" field that the CDC system is setting.
4. Compute and apply system values:
   * Load date
   * Record source
   * A sequence number, which requires you to think about ordering.
   * Hash for all business keys in a record. This is the record of the current table, but also business keys for all foreign keys into that table. The reason why this is important is because all surrogate sequences and primary keys that the source system may have should not have any significance in the data warehouse, unless they are also business keys for that table. This is the reason why I force the staging area to apply the hashes prior to loading it in the raw data vault.
   * (optionally) a hash diff compiled from all or certain attributes in the source data that is used to perform change comparisons to identify duplicates, so we don't load records twice.
5. Remove true duplicates
6. Insert records into staging table
7. (optional) rebuild indexes. Again, not relevant for this setup.

Given the above operations, we see that we should be able to apply a very common pattern to each
source table that we need to ingest. The general strategy is that in the staging area, every record
of interest for the current date partition gets loaded. In those records, the record gets a 
hash key assigned at the very least (even if that resolves to just a surrogate primary key) and
all foreign keys result in inner joins to other tables, so that we can generate the hash key for
the business keys in there. This is because the foreign keys will eventually convert to a link 
of some sort and having the hash key ready in staging allows us to parallellize the following stages
as well. As a matter of fact, it feels wrong to resolve the hashes later. These lookups may have a higher
impact on the source system because of the extra joins for each table, but these lookups have to be made 
'somewhere' and because I believe the source system is where the surrogate keys are relevant, it should be
resolved from there.

In the current implementation I'm using python code to apply the hashing, because it demonstrates that
hashing is possible even if the database engine doesn't implement your hash of interest.

.. important::
    The adventureworks database has some serious design flaws and doesn't expose a lot of useful 
    "natural" business keys that are so important in data vaulting. Because businesses have people that 
    talk about the data a lot, you should find a lot more references, identifiers and natural business keys
    in a true database setup that is actually used by and for people. The main staging setup is done in the
    "adventureworks_*.py" files, which reference the SQL files in the 'sql' folder. In the SQL, you'll see the
    construction of the natural business keys at that stage. The python operator picks up the generated string and
    converts that into a hash using a hash function. The reason to do this per record is because a source database
    system doesn't necessarily have the right capabilities to do this.

There's an important remark to make about "pre-hashing" business keys in the staging area. It means that the 
decisions on what and how to hash are made in the staging area and there may be further issues downstream where
these design decisions can come into play. As the objective is to follow the methodology, we go along with
that and see where this takes us. If you feel unhappy about this, look into setting up a PSA, which will give you
the ability to reload the whole DV at a later stage because all the staging data is preserved.

Another important note: notice how we don't specify what hive staging tables should look like. We're simply
specifying what we want to see in the Hive table. Because Hive is "Schema On Read", you can't enforce nullability
either, so there's no reason to set up a structured destination schema because nothing can be enforced about
it anyway.

Let's look at the flow in more detail:

.. code-block:: python

    args = {
        ....
        # We want to maintain chronological order when loading the datavault
        'depends_on_past': True
    }
    ...

    # specify the purpose for each dag
    RECORD_SOURCE = 'adventureworks.sales'

    # Use a dummy operator as a "knot" to synchronize staging loads
    staging_done = DummyOperator(
        task_id='staging_done',
        dag=dag)

    # A function helps to generalize the parameters,
    # so we can just write 2-3 lines of code to get a 
    # table staged into our datavault
    def create_staging_operator(sql, hive_table, record_source=RECORD_SOURCE):
        t1 = StagePostgresToHiveOperator(
            # The SQL running on postgres
            sql=sql,
            # Create and recreate a hive table with the <name>_yyyymmddthhmmss pattern
            hive_table=hive_table + '_{{ts_nodash}}',
            postgres_conn_id='adventureworks',
            hive_cli_conn_id='hive_advworks_staging',
            # Create a destination table, drop and recreate it every run.
            # Because of the pattern above, we don't need truncates.
            create=True,
            recreate=True,
            record_source=record_source,
            # Specifying the "load_dtm" for this run
            load_dtm='{{execution_date}}',
            # A generalized name
            task_id='stg_{0}'.format(hive_table),
            dag=dag)

        # Putting it in the flow...
        t1 >> staging_done
        return t1

    # Example of the effort of staging a new table
    create_staging_operator(
        sql='staging/salesorderheader.sql',
        hive_table='salesorderheader')

Important design principles to focus on:

* Each staging table is tied to a processing run in airflow and is marked by its own YYYYMMDDTHHMMSS partition. The reason to include a time structure is to think ahead and ingest data in the data warehouse more frequently than once per day. Because we keep staging data separately this way, we don't need to worry about multiple staging cycles in the same table and filter by load_dtm, except for getting the name of the table right. Doing it this allows us to continue to load data in staging even though we can't perhaps (for some reason) load it into the DV yet.
* "depends_on_past" is set to True because we want to force loading data into the datavault in chronological order. The data into staging isn't a critical step, but since each sub pipeline also contains operators for loading the datavault, the whole dag by default is set to the same principle.
* When everything was loaded, we can drop the temp staging table or decide to copy it to a partitioned PSA table.
* New tables can be added by creating a query for it and 3 lines of code, which looks like a great generalization for this process. It is definitely possible to set up a template and generate the required tables from an input table to further ease this process.
* Because of the previous point, the entire table staging process is very generic and predictable.
* There are three distinct parallel processing phases as one would expect from the design of data vault.

Data vault loading flow
-----------------------

Now that data is in staging, it is time to start loading the staging data into datavault. 

Here an important design decision was made:

*Getting the business key hashes for all foreign key is a challenge and I opted to generate all
hashes from the source database using INNER JOINs. The reason is that I'm assuming a CDC slave 
database system that has no other load and good optimization for querying and joining data on subselects
of the driving table.*

I see three different possibilities:

* Generate hashes for all primary+foreign keys from the source system (as in this implementation). The rationale is that surrogate sequence keys frequently used in an RDBMS should only have meaning within the context of that RDBMS, so it is important to apply business keys to business entities as soon as possible.
* Generate hashes for those identified business keys you happen to come across and then use more elaborate joins on the data vault (even joining on satellites in cases).
* Create a cache/lookup table for each source system in the staging area that then becomes an integral part of your data warehouse. The idea is to dissociate the surrogate key from the source system and convert that into a hash without adding significant load on the source system. The rationale is that the data warehouse needs the hash key in order to operate, but the source system has given all the data the DWH is asking for. The DWH itself should be responsible for caching and deliverying the hash key that is needed.

This is the block of code significant for the loading part:

.. code-block:: python

    hubs_done = DummyOperator(
        task_id='hubs_done',
        dag=dag)
    links_done = DummyOperator(
        task_id='links_done',
        dag=dag)
    sats_done =  DummyOperator(
        task_id='sats_done',
        dag=dag)

    def create_hub_operator(hql, hive_table):
        t1 = HiveOperator(
            hql=hql,
            hive_cli_conn_id='hive_datavault_raw',
            schema='dv_raw',
            task_id=hive_table,
            dag=dag)

        staging_done >> t1
        t1 >> hubs_done
        return t1

    def create_link_operator(hql, hive_table):
        t1 = HiveOperator(
            hql=hql,
            hive_cli_conn_id='hive_datavault_raw',
            schema='dv_raw',
            task_id=hive_table,
            dag=dag)

    # hubs
    create_hub_operator('loading/hub_salesorder.hql', 'hub_salesorder')
    ....

    # links
    create_link_operator('loading/link_salesorderdetail.hql', 'link_salesorderdetail')
    ....

Each operator links to the dummy, which gives us the synchronization points. 
Because links may have dependencies outside each functional area (determined by the schema)
some further synchronization is required there.

The loading code follows the same principles as the Data Vault 2.0 default stanzas:

Loading a hub is concerned about creating an 'anchor' around which elements referring to a business
entity resolve. Notice the absence of "record_source" check, so whichever system first sees this 
business key will win the record inserted here.:

.. code-block:: SQL

    INSERT INTO TABLE dv_raw.hub_product
    SELECT DISTINCT
        p.hkey_product,
        p.record_source,
        p.load_dtm,
        p.productnumber
    FROM
        advworks_staging.product_{{ts_nodash}} p
    WHERE
        p.productnumber NOT IN (
            SELECT hub.productnumber FROM dv_raw.hub_product hub
        )

Loading a link concerns itself with tying some hubs together, so the number of lookups increase. Any details related to the characteristics of the relationship are kept in a satellite table tied to the link.

.. code-block:: SQL

    INSERT INTO TABLE dv_raw.link_salesorderdetail
    SELECT DISTINCT
        sod.hkey_salesorderdetail,
        sod.hkey_salesorder,
        sod.hkey_specialoffer,
        sod.hkey_product,
        sod.record_source,
        sod.load_dtm,
        sod.salesorderdetailid
    FROM
               advworks_staging.salesorderdetail_{{ts_nodash}} sod
    WHERE
        NOT EXISTS (
            SELECT 
                    l.hkey_salesorderdetail
            FROM    dv_raw.link_salesorderdetail l
            WHERE 
                    l.hkey_salesorder = sod.hkey_salesorder
            AND     l.hkey_specialoffer = sod.hkey_specialoffer
            AND     l.hkey_product = sod.hkey_product
        )

Loading satellite is the point where chronological ordering becomes truly important. If we don't get the load cycles in chronological order for hubs and links then the "load_dtm" for them will be wrong, but functionally the data vault should keep operating.

For satellites, the chronological ordering determines the version of the entity at a specific time, so it affects what the most current version would look like now. An objective is to avoid loading duplicates, which is the reason we look at characteristics that warrant a new version of the satellite or not. 

Splitting a satellite is a common practice to record data that has different rates of change. For example, if a table has 40 columns as 20 columns change rapidly and 20 more slowly, then if we were to keep everything in the same table, we'd accumulate data twice as fast. By splitting it into 2 separate tables we can keep the detailed changes to a minimum.

.. code-block:: SQL

