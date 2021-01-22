import smtplib
from email.mime.text import MIMEText

__all__ = ("sendEmail",)


def sendEmail(sender, recipients, subject, message, host="localhost", port=25, bccMe=True, disable=False):
    """Send an e-mail

    This is a very simple function to send an e-mail using an open SMTP host.
    In particular, it does not support authentication.

    Parameters
    ----------
    sender : `str`
        Sender's e-mail address (used for ``From`` and ``Bcc``).
    recipient : iterable
        Recipient e-mail addresses.
    subject : `str`
        Subject line.
    message : `str`
        Message body (plain text).
    host : `str`
        SMTP host name.
    port : `int`
        SMTP port number.
    bccMe : `bool`
        Add sender as a ``Bcc``?
    disable : `bool`, optional
        Disable actually sending anything?

    Returns
    -------
    contents : `email.mime.text.MIMEText`
        Contents of the e-mail that was sent.
    """
    if isinstance(recipients, str):
        recipients = [recipients]

    contents = MIMEText(message)
    contents['From'] = sender
    contents['Subject'] = subject
    contents['To'] = ", ".join(recipients)

    target = list(recipients)
    if bccMe:
        contents['Bcc'] = sender
        if sender not in set(target):
            target.append(sender)

    if disable:
        print("Disabled sending the following e-mail:", contents)
    else:
        try:
            smtp = smtplib.SMTP(host, port)
            smtp.ehlo()
            smtp.sendmail(sender, target, contents.as_string())
        finally:
            smtp.close()

    return contents
