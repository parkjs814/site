import json
import logging
import socket
import struct

from django.conf import settings

from judge import event_poster as event

logger = logging.getLogger('judge.judgeapi')
size_pack = struct.Struct('!I')


def judge_request(packet, reply=True):
    sock = socket.create_connection(getattr(settings, 'BRIDGED_DJANGO_CONNECT', None) or
                                    settings.BRIDGED_DJANGO_ADDRESS[0])

    output = json.dumps(packet, separators=(',', ':'))
    output = output.encode('zlib')
    writer = sock.makefile('w', 0)
    writer.write(size_pack.pack(len(output)))
    writer.write(output)
    writer.close()

    if reply:
        reader = sock.makefile('r', -1)
        input = reader.read(size_pack.size)
        if not input:
            raise ValueError('Judge did not respond')
        length = size_pack.unpack(input)[0]
        input = reader.read(length)
        if not input:
            raise ValueError('Judge did not respond')
        reader.close()
        sock.close()

        input = input.decode('zlib')
        result = json.loads(input)
        return result


def judge_submission(submission):
    from .models import ContestSubmission

    try:
        # This is set proactively; it might get unset in judgecallback's on_grading_begin if the problem doesn't
        # actually have pretests stored on the judge.
        submission.is_pretested = ContestSubmission.objects.filter(submission=submission) \
            .values_list('problem__contest__run_pretests_only', flat=True)[0]
    except IndexError:
        pass
    submission.save()

    try:
        response = judge_request({
            'name': 'submission-request',
            'submission-id': submission.id,
            'problem-id': submission.problem.code,
            'language': submission.language.key,
            'source': submission.source,
        })
    except BaseException:
        logger.exception('Failed to send request to judge')
        submission.status = 'IE'
        submission.save()
        success = False
    else:
        if response['name'] != 'submission-received' or response['submission-id'] != submission.id:
            submission.status = 'IE'
            submission.save()
        if submission.problem.is_public:
            event.post('submissions', {'type': 'update-submission', 'id': submission.id,
                                       'contest': submission.contest_key,
                                       'user': submission.user_id, 'problem': submission.problem_id,
                                       'status': submission.status, 'language': submission.language.key})
        success = True
    return success


def abort_submission(submission):
    judge_request({'name': 'terminate-submission', 'submission-id': submission.id}, reply=False)
