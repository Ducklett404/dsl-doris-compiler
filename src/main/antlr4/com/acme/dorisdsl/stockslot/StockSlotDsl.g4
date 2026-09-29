grammar StockSlotDsl;

options { caseInsensitive = true; }

document
    : expression (LIMIT signedInteger COMMA signedInteger)? EOF
    ;

expression       : thenExpression;
thenExpression   : orExpression (THEN orExpression)*;
orExpression     : andExpression (OR andExpression)*;
andExpression    : comparisonExpression (AND comparisonExpression)*;
comparisonExpression
    : additiveExpression ((EQ | NE | GT | GE | LT | LE | APPROX | BETWEEN) additiveExpression)?
    ;
additiveExpression       : multiplicativeExpression ((PLUS | MINUS) multiplicativeExpression)*;
multiplicativeExpression : unaryExpression ((STAR | SLASH) unaryExpression)*;
unaryExpression          : (PLUS | MINUS) unaryExpression | primary;
primary                  : functionCall | literal | LPAREN expression RPAREN;
functionCall             : IDENTIFIER LPAREN argumentList? RPAREN;
argumentList             : expression (COMMA expression)*;
literal                  : PERCENT | NUMBER | INTEGER | STRING | TRUE | FALSE | NULL;
signedInteger            : MINUS? INTEGER;

LIMIT   : 'LIMIT';
THEN    : 'THEN';
OR      : 'OR';
AND     : 'AND';
BETWEEN : 'BETWEEN';
TRUE    : 'TRUE';
FALSE   : 'FALSE';
NULL    : 'NULL';

GE      : '>=';
LE      : '<=';
NE      : '!=' | '<>';
APPROX  : '~=';
EQ      : '=';
GT      : '>';
LT      : '<';
PLUS    : '+';
MINUS   : '-';
STAR    : '*';
SLASH   : '/';
LPAREN  : '(';
RPAREN  : ')';
COMMA   : ',';

PERCENT    : DIGIT+ ('.' DIGIT+)? '%';
NUMBER     : DIGIT+ '.' DIGIT+;
INTEGER    : DIGIT+;
STRING     : '\'' ('\'\'' | ~'\'')* '\'';
IDENTIFIER : [A-Z_] [A-Z_0-9]*;

WS : [ \t\r\n]+ -> skip;
fragment DIGIT : [0-9];
