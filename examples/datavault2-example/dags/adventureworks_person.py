# -*- coding: utf-8 -*-
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function
import airflow
from datetime import datetime, timedelta
from acme.operators.hive_operators import StagePostgresToHiveOperator
from airflow.operators.hive_operator import HiveOperator
from airflow.operators.dummy_operator import DummyOperator
from airflow.models import Variable


args = {
    'owner': 'airflow',
    'start_date': airflow.utils.dates.days_ago(1),
    'provide_context': True,
    # We want to maintain chronological order when loading the datavault
    'depends_on_past': True
}

dag = airflow.DAG(
    'adventureworks_person',
    schedule_interval="@daily",
    dagrun_timeout=timedelta(minutes=60),
    template_searchpath='/usr/local/airflow/sql',
    default_args=args,
    max_active_runs=1)

RECORD_SOURCE = 'adventureworks.person'

staging_done = DummyOperator(
    task_id='staging_done',
    dag=dag)
hubs_done = DummyOperator(
    task_id='hubs_done',
    dag=dag)
links_done = DummyOperator(
    task_id='links_done',
    dag=dag)
sats_done =  DummyOperator(
    task_id='sats_done',
    dag=dag)

staging_done >> hubs_done
hubs_done >> links_done
links_done >> sats_done

# A function helps to generalize the parameters
def create_staging_operator(sql, hive_table, record_source=RECORD_SOURCE):
    t1 = StagePostgresToHiveOperator(
        sql=sql,
        hive_table=hive_table + '_{{ts_nodash}}',
        postgres_conn_id='adventureworks',
        hive_cli_conn_id='hive_advworks_staging',
        create=True,
        recreate=True,
        record_source=record_source,
        load_dtm='{{execution_date}}',
        task_id='stg_{0}'.format(hive_table),
        dag=dag)

    t1 >> staging_done
    return t1

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

    hubs_done >> t1
    t1 >> links_done
    return t1

def create_satellite_operator(hql, hive_table):
    t1 = HiveOperator(
        hql=hql,
        hive_cli_conn_id='hive_datavault_raw',
        schema='dv_raw',
        task_id=hive_table,
        dag=dag)

    links_done >> t1
    t1 >> sats_done
    return t1

# staging
create_staging_operator(sql='staging/address.sql', hive_table='address')
create_staging_operator(sql='staging/countryregion.sql', hive_table='countryregion')
create_staging_operator(sql='staging/person.sql', hive_table='person')
create_staging_operator(sql='staging/stateprovince.sql', hive_table='stateprovince')

# hubs
create_hub_operator('loading/hub_address.hql', 'hub_address')
create_hub_operator('loading/ref_countryregion.hql', 'ref_countryregion')
create_hub_operator('loading/hub_person.hql', 'hub_person')

# links
create_link_operator('loading/link_address_stateprovince.hql', 'link_address_stateprovince')

# satellites
create_satellite_operator('loading/sat_address.hql', 'sat_address')
create_satellite_operator('loading/sat_person.hql', 'sat_person')


if __name__ == "__main__":
    dag.cli()
