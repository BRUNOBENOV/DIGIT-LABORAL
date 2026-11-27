'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
require('../../app/reop_browser_extension/salary-list.js');
const {parsePage, collect} = globalThis.DigitSalaryList;
const employer = '123456', period = '2026-10';
const account = 'Usuario demo con Nro. Patronal: 123456';
function card(id, month = 'Octubre', amount = '1.280') {
  return 'N° De Liquidación Salario: ' + id + ' Horas Ordinarias: 176 Número Patronal: 123456 ' +
   'Empleado: 12.345-SINTÉTICO Período Liquidación: ' + month + ' Periodo Pago Desde: 01/01/2026 ' +
   'Monto Total Ingresos: ' + amount + ' Monto total egresos: 100 Estado: Confirmado Año: 2026 Número de constancia: 001/02';
}
function page(range, cards) {
  return parsePage([account, range, ...cards].join(' '), employer);
}
test('reúne todas las páginas y conserva solo las liquidaciones del mes', async () => {
  const one = page('Mostrando 1 - 2 de 3', [card('400'), card('401','Septiembre')]);
  const two = page('Mostrando 3 - 3 de 3', [card('402','Octubre','0')]);
  const result = await collect(async i => ({...([one,two][i-1]),hasNext:i===1}), employer, period);
  assert.equal(result.inspected,3);
  assert.deepEqual(result.records.map(r => [r.number,r.income,r.status,r.receipt]), [
    ['400',1280,'Confirmado','001/02'],['402',0,'Confirmado','001/02'],
  ]);
});
test('un listado vacío requiere evidencia y una página perdida o repetida bloquea la lectura', async () => {
  assert.equal(parsePage(account + ' No se encontraron registros', employer).total,0);
  assert.throws(() => parsePage(account,employer));
  assert.throws(() => parsePage(account + ' Sin registros','888'));
  assert.throws(() => page('Mostrando 1 - 2 de 9',[card('401')]));
  assert.throws(() => page('Mostrando 1 - 1 de 1',[card('401').replace('Monto Total Ingresos:', 'Salario básico:')]));
  const first = page('Mostrando 1 - 1 de 2',[card('401')]);
  await assert.rejects(collect(async () => ({...first,hasNext:false}),employer,period),/páginas/);
  const second = page('Mostrando 2 - 2 de 2',[card('401')]);
  await assert.rejects(collect(async i => ({...(i===1?first:second),hasNext:i===1}),employer,period),/repitió/);
});

test('historical rows count without requiring unrelated fields; selected rows fail closed', async () => {
  const old = card('400','Septiembre').replace('Monto Total Ingresos:', 'Salario básico:');
  const current = card('401');
  const text = [account,'Mostrando 1 - 2 de 2',old,current].join(' ');
  const data = parsePage(text,employer,period);
  const result = await collect(async () => ({...data,hasNext:false}),employer,period);
  assert.equal(result.inspected,2);
  assert.deepEqual(result.records.map(r=>r.number),['401']);
  assert.throws(() => parsePage(text,employer,'2026-09'), /400.*total de ingresos/);
  assert.throws(() => parsePage(text.replace('Período Liquidación: Septiembre','Período Liquidación: desconocido'),employer,period), /400.*mes o año/);
  assert.throws(() => parsePage(text.replace('Número Patronal: 123456','Número Patronal: 999'),employer,period), /400.*patronal/);
});
