import os
import boto3
import json
import time
import urllib.parse
import re
stepFunction = boto3.client('stepfunctions')
sqs = boto3.client('sqs')
step_function_arn = os.environ["STEP_FUNCTION_ARN"]
raw_queue_url = os.environ["RAW_QUEUE_URL"]
sqs_poll_size = int(os.environ["SQS_POLL_SIZE"]) 
file_system_path=os.environ['FILE_SYSTEM_PATH']

readCNT = 0
deleteCNT = 0
depth = 0
fileCNT = 0
dirCNT = 0

def cleanEFS():
    global readCNT
    global deleteCNT
    global fileCNT
    global dirCNT

    now = time.time()
    for filename in os.listdir(file_system_path):
        try:
            readCNT = readCNT +1
            full_path = os.path.join(file_system_path, filename)
    
            
            filestamp = os.stat(os.path.join(file_system_path, filename)).st_ctime
            filecompare = now - 240
        
            if  filestamp < filecompare:
                if os.path.isdir(full_path):
                    delDir(full_path)
                    deleteCNT = deleteCNT + 1
                else:
                    readCNT = readCNT + 1
                    os.remove(os.path.join(file_system_path, filename))
                    deleteCNT = deleteCNT + 1
                    fileCNT = fileCNT + 1
        except Exception as e:
            if "No such file or directory" in str(e):
                print("Ignoring File Cleanup error {}".format(e))
            else:
                raise e
    print("OK: processed={} deleted={} files={} directories={}".format(readCNT, deleteCNT, fileCNT, dirCNT))

def delDir(base_dir):
    global depth
    global readCNT
    global deleteCNT
    global fileCNT
    global dirCNT
    depth = depth + 1

    nix_root = re.findall("^\/$", base_dir)
    current = re.findall("^\.$", base_dir)
    win_root = re.findall("^[a-z,A-Z]\:\\\\$", base_dir)

    if os.path.exists(base_dir) and os.path.isdir(base_dir):
        if nix_root or current or win_root or base_dir == os.getcwd() :
            print("Cannot clear {}".format(base_dir))
            raise Exception("Invalid path").with_traceback(tracebackobj)
    else:
        print("Invalid path {}".format(base_dir))
        raise Exception("Invalid path").with_traceback(tracebackobj)

    #print("Clearing {0}".format(base_dir))

    for the_file in os.listdir(base_dir):
        readCNT = readCNT + 1
        file_path = os.path.join(base_dir,the_file)

        if os.path.isfile(file_path):
            os.unlink(file_path)
            deleteCNT = deleteCNT + 1
            fileCNT = fileCNT + 1
        else:
            delDir(file_path)
            os.rmdir(file_path)
            deleteCNT = deleteCNT + 1
            dirCNT = dirCNT + 1

    depth = depth - 1
    if depth == 0:
        os.rmdir(base_dir)
        deleteCNT = deleteCNT + 1
        dirCNT = dirCNT + 1


def triggerSF(bucket_name, file_key):
    try:
        input= {
            'bucket_name': bucket_name,
            'file_key': file_key
        }
        print("Bucket Name: {}".format(bucket_name))
        print("File Key {}".format(file_key))
        response = stepFunction.start_execution(
            stateMachineArn=step_function_arn,
            input = json.dumps(input, indent=4)
        )
        print("Invoked step-function successfully: {}".format(response['executionArn']))
    except Exception as e:
        print(str(e))
        print("Failed to trigger stepfunction")
        raise e

def getMessagesFromQueue(qUrl,):
    # Receive message from SQS queue
    response = sqs.receive_message(
        QueueUrl=qUrl,
        MaxNumberOfMessages=1,
        VisibilityTimeout=60 #14400
    )

    print('SQS Response Recieved:')
    print(response)

    if('Messages' in response):
        return response['Messages']
    else:
        print("No messages in queue.")
        return None

def lambda_handler(event, context): 
    cleanEFS()
    queue_poll = 0
    while queue_poll < sqs_poll_size:
        queue_poll += 1
        messages = getMessagesFromQueue(raw_queue_url)
        totalMessages = 0
        if(messages):
            totalMessages = len(messages)
            print("Total messages: {}".format(totalMessages))
            for message in messages:
                receipt_handle = message['ReceiptHandle']
                messageBody = json.loads(message['Body'])
                subMessage = json.loads(messageBody['Message'])
                if "Records" in subMessage:
                    bucket_name = subMessage['Records'][0]['s3']['bucket']['name']
                    object_key = subMessage['Records'][0]['s3']['object']['key']
                    if "onbase/documents/" in object_key and ".aws-datasync/" not in object_key and "onbase/documents/daily/" != object_key and "onbase/documents/historical/" != object_key and "onbase/documents/daily/DailyUpdates/" != object_key and "raw-data" in bucket_name:
                        triggerSF(bucket_name, object_key)
                    print('Deleting item from queue...')
                # Delete received message from queue
                sqs.delete_message(
                    QueueUrl=raw_queue_url,
                    ReceiptHandle=receipt_handle
                )
                print('Deleted item from queue...')
        else:
            queue_poll = sqs_poll_size
