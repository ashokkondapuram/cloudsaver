import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseMoney,moneyInput,formatMoney,containsCardNumber,httpsUrlError} from '../lib/format.ts';

test('payment inputs preserve currency minor units and reject precision loss',()=>{
  assert.equal(parseMoney('1,200.50','USD'),120050);
  assert.equal(parseMoney('12.345','KWD'),12345);
  assert.equal(parseMoney('1200','JPY'),1200);
  assert.equal(parseMoney('1.001','USD'),null);
  assert.equal(parseMoney('9999999999999.999','KWD'),null);
  assert.equal(parseMoney('-1','USD'),null);
  assert.equal(moneyInput(12345,'KWD'),'12.345');
  assert.equal(formatMoney(null,'USD'),'—');
});

test('billing link validation rejects credential and tracking payloads',()=>{
  for(const url of ['http://billing.example.com','https://user:password@billing.example.com','https://billing.example.com?token=private','https://billing.example.com/#secret'])assert.notEqual(httpsUrlError(url),'');
  assert.equal(httpsUrlError('https://billing.example.com/invoices'),'');
});

test('payment notes identify card-number sequences before submission',()=>{
  assert.equal(containsCardNumber('Test payment 4111 1111 1111 1111'),true);
  assert.equal(containsCardNumber('Reference INV-2026-1025'),false);
});
