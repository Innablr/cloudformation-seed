const AWS = require('aws-sdk');
const response = require('cfn-response');
const awsRegion = process.env.AWS_REGION || 'eu-west-2';

function decryptValue(v) {
    const kms = new AWS.KMS({region: awsRegion});
    const blob = new Buffer(v, 'base64');
    return kms.decrypt({CiphertextBlob: blob}).promise();
}

exports.handler = (event, context, callback) => {
    if (event.RequestType === 'Delete') {
        console.log('Resourse deletion requested, ignoring...');
        response.send(event, context, response.SUCCESS);
        return;
    }
    const encryptedValue = event.ResourceProperties.EncryptedValue;
    const binRequired = ['yes', 'true'].includes((event.ResourceProperties.ReturnBinary || '').toLowerCase());
    console.log('Encrypted value is [%s]', encryptedValue);
    console.log('Returning [%s]', binRequired ? 'binary' : 'text');
    if (encryptedValue === undefined) {
        console.error('Encrypted value not set, properties were: %j', event.ResourceProperties);
        response.send(event, context, response.FAILED, {errorMessage: 'Encrypted value not set'});
        return;
    }
    decryptValue(encryptedValue)
        .then(r => r.Plaintext)
        .then(r => binRequired ? r : r.toString('utf8'))
        .then(r => response.send(event, context, response.SUCCESS, {Text: r}))
        .catch(function(e) {
            console.error('Decryption failed: %s', e);
            response.send(event, context, response.FAILED, {errorMessage: e});
        });
};