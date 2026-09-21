grammar SlotDsl;

options { caseInsensitive = true; }

query                    : expression limitClause? EOF;
limitClause              : LIMIT signedInt COMMA signedInt;
signedInt                : MINUS? INT;
expression               : thenExpression;
thenExpression           : orExpression (THEN orExpression)*;
orExpression             : andExpression (OR andExpression)*;
andExpression            : comparisonExpression (AND comparisonExpression)*;
comparisonExpression     : additiveExpression (comparisonOperator additiveExpression | BETWEEN STRING)?;
comparisonOperator       : EQ | NE | GT | GE | LT | LE | APPROX;
additiveExpression       : multiplicativeExpression ((PLUS | MINUS) multiplicativeExpression)*;
multiplicativeExpression : unaryExpression ((STAR | SLASH) unaryExpression)*;
unaryExpression          : (PLUS | MINUS) unaryExpression | primary;
primary                  : functionCall | literal | LPAREN expression RPAREN;
functionCall             : IDENTIFIER LPAREN slotList? RPAREN;
slotList                 : STRING (COMMA STRING)*;
literal                  : PERCENT | DECIMAL | INT | STRING | TRUE | FALSE;

AND     : 'AND';
OR      : 'OR';
THEN    : 'THEN';
BETWEEN : 'BETWEEN';
LIMIT   : 'LIMIT';
TRUE    : 'TRUE';
FALSE   : 'FALSE';
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
DECIMAL    : DIGIT+ '.' DIGIT+;
INT        : DIGIT+;
STRING     : '\'' ('\'\'' | ~'\'')* '\'';
IDENTIFIER : [A-Z_] [A-Z_0-9]*;
WS         : [ \t\r\n]+ -> skip;
fragment DIGIT : [0-9];
