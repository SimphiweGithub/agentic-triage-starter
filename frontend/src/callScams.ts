/** Plain-language call scams shown when the person gets a call. Edit the wording here; nothing else needs to change. */
export type CallScam = { id: string; title: string; text: string }

export const CALL_SCAMS: CallScam[] = [
  { id: 'bank', title: '“Your bank is calling”', text: 'They say your account is in danger and ask for a PIN, OTP or card number. A real bank never asks for these.' },
  { id: 'family', title: '“Your grandchild is in trouble”', text: 'An urgent call asking for money or airtime. Stop and phone your family member on the number you already have.' },
  { id: 'prize', title: 'A prize or lottery win', text: 'You are told you won, but must pay a fee first. Real prizes never cost money to collect.' },
  { id: 'sim', title: 'SIM swap or courier call', text: 'They ask you to read out a code sent by SMS. That code lets them take over your number and your bank.' },
  { id: 'fines', title: 'Tax or fines caller', text: 'Threats of arrest or penalties unless you pay now. Government offices do not demand payment over the phone.' },
  { id: 'tech', title: 'Fake tech support or utility', text: 'They want access to your phone, or say your power or data will be cut off. Do not install anything they ask for.' },
]

export const CALL_RULE = 'Hang up. Then call the number on your card or bill yourself.'
