# coding: utf-8

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils.translation import ugettext_lazy as _

from common.utils import get_logger, get_object_or_none
from orgs.utils import tmp_to_org
from .celery.decorator import (
    register_as_period_task, after_app_ready_start
)
from .celery.utils import (
    create_or_update_celery_periodic_tasks, get_celery_periodic_task,
    disable_celery_periodic_task, delete_celery_periodic_task
)
from .models import Job, JobExecution
from .notifications import ServerPerformanceCheckUtil

logger = get_logger(__file__)


def job_task_activity_callback(self, job_id, trigger):
    job = get_object_or_none(Job, id=job_id)
    if not job:
        return
    resource_ids = [job.id]
    org_id = job.org_id
    return resource_ids, org_id


@shared_task(
    soft_time_limit=60, queue="ansible", verbose_name=_("Run ansible task"),
    activity_callback=job_task_activity_callback
)
def run_ops_job(job_id):
    job = get_object_or_none(Job, id=job_id)
    with tmp_to_org(job.org):
        execution = job.create_execution()
        execution.creator = job.creator
        run_ops_job_execution(execution.id)
        try:
            execution.start()
        except SoftTimeLimitExceeded:
            execution.set_error('Run timeout')
            logger.error("Run adhoc timeout")
        except Exception as e:
            execution.set_error(e)
            logger.error("Start adhoc execution error: {}".format(e))


def job_execution_task_activity_callback(self, execution_id, trigger):
    execution = get_object_or_none(JobExecution, id=execution_id)
    if not execution:
        return
    resource_ids = [execution.id]
    org_id = execution.org_id
    return resource_ids, org_id


@shared_task(
    soft_time_limit=60, queue="ansible", verbose_name=_("Run ansible task execution"),
    activity_callback=job_execution_task_activity_callback
)
def run_ops_job_execution(execution_id, **kwargs):
    execution = get_object_or_none(JobExecution, id=execution_id)
    try:
        with tmp_to_org(execution.org):
            execution.start()
    except SoftTimeLimitExceeded:
        execution.set_error('Run timeout')
        logger.error("Run adhoc timeout")
    except Exception as e:
        execution.set_error(e)
        logger.error("Start adhoc execution error: {}".format(e))


@shared_task(verbose_name=_('Clear celery periodic tasks'))
@after_app_ready_start
def clean_celery_periodic_tasks():
    """清除celery定时任务"""
    need_cleaned_tasks = [
        'handle_be_interrupted_change_auth_task_periodic',
    ]
    logger.info('Start clean celery periodic tasks: {}'.format(need_cleaned_tasks))
    for task_name in need_cleaned_tasks:
        logger.info('Start clean task: {}'.format(task_name))
        task = get_celery_periodic_task(task_name)
        if task is None:
            logger.info('Task does not exist: {}'.format(task_name))
            continue
        disable_celery_periodic_task(task_name)
        delete_celery_periodic_task(task_name)
        task = get_celery_periodic_task(task_name)
        if task is None:
            logger.info('Clean task success: {}'.format(task_name))
        else:
            logger.info('Clean task failure: {}'.format(task))


@shared_task(verbose_name=_('Create or update periodic tasks'))
@after_app_ready_start
def create_or_update_registered_periodic_tasks():
    from .celery.decorator import get_register_period_tasks
    for task in get_register_period_tasks():
        create_or_update_celery_periodic_tasks(task)


@shared_task(verbose_name=_("Periodic check service performance"))
@register_as_period_task(interval=3600)
def check_server_performance_period():
    ServerPerformanceCheckUtil().check_and_publish()
